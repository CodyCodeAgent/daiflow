"""Runner resolution and instantiation service.

Provides a three-layer lookup (task → project → global default) to determine
which RunnerConfig to use, then instantiates the appropriate AbstractAgentRunner.

Lookup priority:
  1. task.runner_id
  2. project.runner_id
  3. settings key "default_runner_id"
  4. None → caller falls back to legacy Cody settings (backward compat)
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.exceptions import ConfigurationError
from daiflow.models import Project, RunnerConfig, Setting, Task
from daiflow.runners.base import AbstractAgentRunner

logger = logging.getLogger(__name__)


async def resolve_runner_config(
    db: AsyncSession,
    project_id: str | None = None,
    task_id: str | None = None,
) -> RunnerConfig | None:
    """Return the RunnerConfig to use, or None for legacy Cody fallback.

    Lookup order:
      1. task.runner_id (if task_id given)
      2. project.runner_id (if project_id given)
      3. settings.default_runner_id
      4. None
    """
    # 1. Task-level override
    if task_id:
        task = await db.get(Task, task_id)
        if task and task.runner_id:
            rc = await db.get(RunnerConfig, task.runner_id)
            if rc:
                return rc

    # 2. Project-level override
    if project_id:
        project = await db.get(Project, project_id)
        if project and project.runner_id:
            rc = await db.get(RunnerConfig, project.runner_id)
            if rc:
                return rc

    # 3. Global default
    setting = await db.get(Setting, "default_runner_id")
    if setting and setting.value:
        rc = await db.get(RunnerConfig, setting.value)
        if rc:
            return rc

    return None


async def build_runner_from_config(
    rc: RunnerConfig | None,
    db: AsyncSession,
    workdir: str,
    allowed_roots: list[str],
    skill_dir: str | None = None,
    tools: list | None = None,
) -> AbstractAgentRunner:
    """Instantiate a runner from a RunnerConfig.

    Args:
        rc: RunnerConfig to use. None triggers legacy Cody settings fallback.
        db: Database session (used for legacy Cody settings lookup).
        workdir: Primary working directory for the runner.
        allowed_roots: Additional directories the runner may access.
        skill_dir: Optional skill/knowledge directory (Cody-specific).

    Returns:
        An AbstractAgentRunner ready to be used as an async context manager.
    """
    runner_type = rc.type if rc else "cody"

    if runner_type == "cody":
        cfg = json.loads(rc.config) if rc and rc.config else {}
        client = await _build_cody_client_from_cfg(db, cfg, workdir, allowed_roots, skill_dir, tools=tools)
        from daiflow.runners.cody_runner import CodyRunner
        return CodyRunner(client)

    elif runner_type == "claude_code":
        if not rc:
            raise ConfigurationError("RunnerConfig required for claude_code runner")
        cfg = json.loads(rc.config) if rc.config else {}
        # api_key optional: Claude Code can use ANTHROPIC_API_KEY env var
        api_key = (cfg.get("api_key") or "").strip()
        model = cfg.get("model") or None
        max_turns = int(cfg["max_turns"]) if cfg.get("max_turns") else None
        from daiflow.runners.claude_code_runner import ClaudeCodeRunner
        return ClaudeCodeRunner(
            workdir=workdir,
            allowed_roots=allowed_roots,
            api_key=api_key,
            model=model,
            max_turns=max_turns,
        )

    elif runner_type == "cursor":
        if not rc:
            raise ConfigurationError("RunnerConfig required for cursor runner")
        cfg = json.loads(rc.config) if rc.config else {}
        api_key = (cfg.get("api_key") or "").strip()
        model = cfg.get("model") or None
        max_turns = int(cfg["max_turns"]) if cfg.get("max_turns") else None
        from daiflow.services.mcp_service import get_active_mcp_servers
        mcp_servers = await get_active_mcp_servers(db)
        from daiflow.runners.cursor_runner import CursorRunner
        return CursorRunner(
            workdir=workdir,
            allowed_roots=allowed_roots,
            api_key=api_key,
            model=model,
            max_turns=max_turns,
            skill_dir=skill_dir,
            mcp_servers=mcp_servers,
        )

    else:
        raise ConfigurationError(f"Unknown runner type: {runner_type!r}")


async def _build_cody_client_from_cfg(
    db: AsyncSession,
    cfg: dict,
    workdir: str,
    allowed_roots: list[str],
    skill_dir: str | None,
    tools: list | None = None,
):
    """Build an AsyncCodyClient from either a RunnerConfig's config dict or legacy DB settings."""
    from daiflow.config import CODY_DB_PATH
    from daiflow.exceptions import ConfigurationError as _CE
    from daiflow.models import Setting
    from sqlalchemy import select

    if cfg:
        # RunnerConfig-based: use fields from the config JSON
        model = cfg.get("model", "")
        base_url = cfg.get("base_url", "")
        api_key = cfg.get("api_key", "")
    else:
        # Legacy fallback: read from settings table
        from daiflow.services.cody_service import _SETTINGS_KEYS
        result = await db.execute(
            select(Setting).where(Setting.key.in_(_SETTINGS_KEYS))
        )
        settings = {s.key: s.value for s in result.scalars().all()}
        model = settings.get("cody_model", "")
        base_url = settings.get("cody_base_url", "")
        api_key = settings.get("cody_api_key", "")

    if not all([model, base_url, api_key]):
        raise _CE(
            "AI model not configured. Please configure a runner in Settings."
        )

    from cody import Cody

    builder = (
        Cody()
        .workdir(workdir)
        .model(model)
        .base_url(base_url)
        .api_key(api_key)
        .db_path(str(CODY_DB_PATH))
    )

    roots = [workdir]
    if allowed_roots:
        roots.extend(r for r in allowed_roots if r != workdir)
    builder = builder.allowed_roots(roots).strict_read_boundary(True)

    if skill_dir and hasattr(builder, "skill_dir"):
        builder = builder.skill_dir(skill_dir)

    if hasattr(builder, "mcp_http_server"):
        from daiflow.services.mcp_service import get_active_mcp_servers
        servers = await get_active_mcp_servers(db)
        for name, url, headers in servers:
            builder = builder.mcp_http_server(name, url=url, headers=headers)
        if servers and hasattr(builder, "auto_start_mcp"):
            builder = builder.auto_start_mcp(True)

    # Register custom tools
    if tools and hasattr(builder, "tool"):
        for tool_fn in tools:
            builder = builder.tool(tool_fn)

    return builder.build()


def mask_runner_config(config: dict) -> dict:
    """Return a copy of the config dict with api_key masked for API responses."""
    masked = dict(config)
    if "api_key" in masked and masked["api_key"]:
        v = masked["api_key"]
        if len(v) > 8:
            masked["api_key"] = v[:4] + "*" * (len(v) - 8) + v[-4:]
        else:
            masked["api_key"] = "****"
    return masked
