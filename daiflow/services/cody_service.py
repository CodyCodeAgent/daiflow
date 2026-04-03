import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import CODY_DB_PATH
from daiflow.exceptions import ConfigurationError
from daiflow.models import Setting

logger = logging.getLogger(__name__)

# Settings keys needed for Cody AI client
_SETTINGS_KEYS = ["cody_model", "cody_base_url", "cody_api_key"]


async def get_cody_settings(db: AsyncSession) -> dict:
    """Fetch cody_model, cody_base_url, cody_api_key settings."""
    result = await db.execute(
        select(Setting).where(Setting.key.in_(_SETTINGS_KEYS))
    )
    settings = {s.key: s.value for s in result.scalars().all()}
    return settings


async def build_cody_client(
    db: AsyncSession,
    workdir: str,
    allowed_roots: list[str] | None = None,
    skill_dir: str | None = None,
    tools: list | None = None,
):
    """Create an AsyncCodyClient from settings."""
    from cody import Cody

    settings = await get_cody_settings(db)
    model = settings.get("cody_model", "")
    base_url = settings.get("cody_base_url", "")
    api_key = settings.get("cody_api_key", "")

    if not all([model, base_url, api_key]):
        raise ConfigurationError("AI model not configured. Please set cody_model, cody_base_url, and cody_api_key in Settings.")

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
        roots.extend(allowed_roots)
    builder = builder.allowed_roots(roots).strict_read_boundary(True)

    if skill_dir:
        if hasattr(builder, "skill_dir"):
            builder = builder.skill_dir(skill_dir)
        else:
            logger.warning(
                "Cody SDK does not support skill_dir() — upgrade to cody-ai>=1.10.2 for explicit skill directory support"
            )

    # Attach MCP HTTP servers
    if hasattr(builder, "mcp_http_server"):
        from daiflow.services.mcp_service import get_active_mcp_servers

        servers = await get_active_mcp_servers(db)
        for name, url, headers in servers:
            builder = builder.mcp_http_server(name, url=url, headers=headers)
        if servers and hasattr(builder, "auto_start_mcp"):
            builder = builder.auto_start_mcp(True)
    else:
        logger.debug("Cody SDK does not support mcp_http_server() — MCP servers skipped")

    # Register custom tools
    if tools and hasattr(builder, "tool"):
        for tool_fn in tools:
            builder = builder.tool(tool_fn)

    return builder.build()


async def build_task_cody_client(db: AsyncSession, task_id: str, project_id: str):
    """Build a Cody client configured for a task context.

    Convenience wrapper that resolves task directory, allowed roots,
    and skill directory — the common pattern used by task_service,
    chat_service, and review_service.
    """
    from daiflow.config import get_task_dir, get_task_skills_dir
    from daiflow.services.task_service import get_task_context

    task_dir = get_task_dir(task_id)
    _, allowed_roots = await get_task_context(db, task_id, project_id)
    skill_dir = str(get_task_skills_dir(task_id))
    return await build_cody_client(db, str(task_dir), allowed_roots, skill_dir=skill_dir)


async def build_runner(
    db: AsyncSession,
    workdir: str,
    allowed_roots: list[str],
    skill_dir: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
    tools: list | None = None,
):
    """Runner factory: resolve config via three-layer lookup and instantiate runner.

    Args:
        db: Database session.
        workdir: Primary working directory for the runner.
        allowed_roots: Additional directories the runner may access.
        skill_dir: Optional skill directory (Cody-specific).
        project_id: Used for project-level runner override lookup.
        task_id: Used for task-level runner override lookup.
        tools: Optional list of custom tool functions (Cody-specific).

    Returns:
        An AbstractAgentRunner ready for use as an async context manager.
    """
    from daiflow.services.runner_service import build_runner_from_config, resolve_runner_config

    rc = await resolve_runner_config(db, project_id=project_id, task_id=task_id)
    return await build_runner_from_config(rc, db, workdir, allowed_roots, skill_dir, tools=tools)


async def build_task_runner(db: AsyncSession, task_id: str, project_id: str):
    """Build a runner configured for a task context.

    Convenience wrapper equivalent to build_task_cody_client() but returns
    an AbstractAgentRunner honouring the task/project/global runner config.
    """
    from daiflow.config import get_task_dir, get_task_skills_dir
    from daiflow.services.task_service import get_task_context

    task_dir = get_task_dir(task_id)
    _, allowed_roots = await get_task_context(db, task_id, project_id)
    skill_dir = str(get_task_skills_dir(task_id))
    return await build_runner(
        db, str(task_dir), allowed_roots, skill_dir,
        project_id=project_id, task_id=task_id,
    )


def append_path_boundary(prompt: str, workdir: str, allowed_roots: list[str]) -> str:
    """Append path boundary instructions to a prompt.

    Soft restriction via prompt to prevent Cody from accessing files
    outside allowed_roots (complements strict_read_boundary in SDK).
    """
    all_roots = [workdir]
    for r in (allowed_roots or []):
        if r != workdir:
            all_roots.append(r)
    roots_list = "\n".join(f"- {r}" for r in all_roots)
    return prompt + (
        "\n\n## IMPORTANT: Path Boundary\n"
        "You MUST ONLY access files within the following directories:\n"
        f"{roots_list}\n"
        "Do NOT explore parent directories, sibling directories, or any path outside the listed roots. "
        "Do NOT use exec_command (ls, find, cat, etc.) to access files outside these directories."
    )
