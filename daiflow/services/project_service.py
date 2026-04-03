import asyncio
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from daiflow.config import utc_iso
from daiflow.database import get_background_db
from daiflow.models import ProjectRepo, Session, SessionStatus
from daiflow.prompts import CONSTITUTION_PROMPT_TEMPLATE, KNOWLEDGE_PROMPTS, PROJECT_MD_PROMPT
from daiflow.services.cody_service import append_path_boundary
from daiflow.services.git_service import clone_or_pull, get_head_hash
from daiflow.services.settings_service import get_language_setting
from daiflow.services.skill_service import get_project_dir
from daiflow.session_runner import SessionRunner, append_log
from daiflow.workflow.pipeline import run_simple_task
from daiflow.session_ids import project_init as _init_sid, project_init_bus as _init_bus
from daiflow.ws_manager import WSManager, ws_manager as _default_ws_manager

logger = logging.getLogger(__name__)

# Knowledge types per layer
LAYER_2_TYPES = {
    "frontend": ["frontend-structure", "business-flow", "component-usage"],
    "backend": ["backend-structure"],
    "fullstack": ["frontend-structure", "backend-structure", "business-flow", "component-usage"],
    "custom": ["backend-structure", "business-flow"],
}
LAYER_3_TYPES = ["module-overview", "api-interaction", "data-entity", "dependencies"]


def repo_dir_name(git_url: str) -> str:
    """Extract a safe directory name from a git URL.

    e.g. 'https://github.com/org/my-repo.git' -> 'my-repo'
         'git@github.com:org/my-repo.git'     -> 'my-repo'
    """
    # Take the last path segment, strip .git suffix
    name = git_url.rstrip("/").rsplit("/", 1)[-1]
    name = name.rsplit(":", 1)[-1]  # handle ssh-style git@host:org/repo
    if name.endswith(".git"):
        name = name[:-4]
    # Sanitize: keep only word chars, hyphens, dots
    name = re.sub(r'[^\w.\-]', '_', name)
    return name or "repo"


def _resolve_allowed_roots(project_dir: Path, repos: list) -> list[str]:
    """Resolve analysis paths for each repo under a project directory.

    Uses the same repo_dir_name logic as task_service.resolve_repo_path,
    but resolves relative to the project dir (not task dir).
    """
    from daiflow.services.task_service import resolve_repo_path_in

    return resolve_repo_path_in(project_dir, repos)


def _build_repos_context(repos: list, allowed_roots: list[str] | None = None) -> str:
    """Format repo list into a readable context string for prompts."""
    lines = []
    for r in repos:
        label = r.repo_type_label or r.repo_type
        path = r.local_path or r.git_url or "unknown"
        desc = f" — {r.description}" if r.description else ""
        sub = ""
        if getattr(r, "sub_path", None):
            sub = (
                f" (Focus on `{r.sub_path}` subdirectory. "
                "Other files in this repo do not need to be explored, "
                "but may be referenced if needed for understanding dependencies.)"
            )
        lines.append(f"- [{label}] {path}{desc}{sub}")
    return "\n".join(lines) if lines else "(no repositories configured)"


def compute_init_sessions(project_id: str, repos: list) -> list[dict]:
    """Compute all session records needed for project init.

    Deduplicates Layer 2 sessions when multiple repos share a knowledge type.
    """
    sessions = []
    seen_session_ids: set[str] = set()

    # Layer 1: resource prep (repo_clone)
    sessions.append({
        "session_id": _init_sid(project_id, "repo_clone"),
        "type": "init",
        "ref_id": project_id,
        "layer": 1,
    })

    # Layer 2: per-repo knowledge (deduplicated by knowledge type)
    for repo in repos:
        repo_type = repo.repo_type
        types = LAYER_2_TYPES.get(repo_type, [])
        for kt in types:
            sid = _init_sid(project_id, kt)
            if sid not in seen_session_ids:
                seen_session_ids.add(sid)
                sessions.append({
                    "session_id": sid,
                    "type": "init",
                    "ref_id": project_id,
                    "layer": 2,
                })

    # Layer 3: cross-repo knowledge
    for kt in LAYER_3_TYPES:
        sessions.append({
            "session_id": _init_sid(project_id, kt),
            "type": "init",
            "ref_id": project_id,
            "layer": 3,
        })

    # Layer 4: project.md
    sessions.append({
        "session_id": _init_sid(project_id, "project_md"),
        "type": "init",
        "ref_id": project_id,
        "layer": 4,
    })

    # Layer 5: constitution.md (synthesizes project principles)
    sessions.append({
        "session_id": _init_sid(project_id, "constitution"),
        "type": "init",
        "ref_id": project_id,
        "layer": 5,
    })

    return sessions


async def _run_constitution(
    project_id: str,
    project_dir: Path,
    allowed_roots: list[str],
    project_bus: str,
    lang: str | None,
) -> None:
    """Layer 5: generate constitution.md that captures core development principles."""
    sid = _init_sid(project_id, "constitution")
    async with get_background_db() as layer5_db:
        prompt = CONSTITUTION_PROMPT_TEMPLATE.format(output_path=str(project_dir))
        from daiflow.services.cody_service import append_path_boundary, build_runner
        prompt = append_path_boundary(prompt, str(project_dir), allowed_roots)
        agent_runner = await build_runner(
            layer5_db, str(project_dir), allowed_roots, project_id=project_id
        )
        session_runner = SessionRunner(agent_runner)
        async with agent_runner:
            await session_runner.run(
                layer5_db, sid, prompt,
                extra_channels=[project_bus], language=lang,
            )


async def _run_knowledge_task(
    project_dir: Path,
    allowed_roots: list[str],
    repos: list,
    session_id: str,
    knowledge_type: str,
    project_bus: str,
    lang: str | None,
    project_id: str | None = None,
):
    """Run a single knowledge generation task with its own DB session."""
    async with get_background_db() as task_db:
        skills_dir = project_dir / "skills" / knowledge_type
        skills_dir.mkdir(parents=True, exist_ok=True)
        repos_context = _build_repos_context(repos)
        prompt = KNOWLEDGE_PROMPTS[knowledge_type].format(
            output_path=str(skills_dir), repos_context=repos_context,
        )
        prompt = append_path_boundary(prompt, str(project_dir), allowed_roots)
        from daiflow.services.cody_service import build_runner
        agent_runner = await build_runner(task_db, str(project_dir), allowed_roots, project_id=project_id)
        session_runner = SessionRunner(agent_runner)
        async with agent_runner:
            await session_runner.run(task_db, session_id, prompt, extra_channels=[project_bus], language=lang)


async def _run_layer(
    layer_sessions: list,
    layer_num: int,
    project_dir: Path,
    allowed_roots: list[str],
    repos: list,
    project_bus: str,
    lang: str | None,
    project_id: str | None = None,
) -> bool:
    """Run all knowledge tasks in a layer concurrently. Returns True if all succeeded."""
    layer_tasks = []
    session_ids = []
    for s in layer_sessions:
        kt = s.session_id.split(":")[-1]
        if kt in KNOWLEDGE_PROMPTS:
            layer_tasks.append(_run_knowledge_task(
                project_dir, allowed_roots, repos, s.session_id, kt, project_bus, lang,
                project_id=project_id,
            ))
            session_ids.append(s.session_id)
    if not layer_tasks:
        return True

    results = await asyncio.gather(*layer_tasks, return_exceptions=True)
    has_failure = False
    for s_id, r in zip(session_ids, results):
        if isinstance(r, Exception):
            has_failure = True
            logger.error("Layer %d task %s failed: %s", layer_num, s_id, r)
    return not has_failure


async def _run_layer4(
    project_id: str,
    project_dir: Path,
    allowed_roots: list[str],
    project_bus: str,
    lang: str | None,
):
    """Run Layer 4: generate project.md index."""
    sid = _init_sid(project_id, "project_md")
    async with get_background_db() as layer4_db:
        prompt = PROJECT_MD_PROMPT.format(output_path=str(project_dir))
        from daiflow.services.cody_service import build_runner
        agent_runner = await build_runner(layer4_db, str(project_dir), allowed_roots, project_id=project_id)
        session_runner = SessionRunner(agent_runner)
        async with agent_runner:
            await session_runner.run(layer4_db, sid, prompt, extra_channels=[project_bus], language=lang)


async def _finalize_init(db, project_id: str, project_bus: str, ws: WSManager | None = None):
    """Mark remaining WAITING init sessions as FAILED and send final done event."""
    ws = ws or _default_ws_manager
    result = await db.execute(
        select(Session).where(
            Session.ref_id == project_id,
            Session.type == "init",
            Session.status == SessionStatus.WAITING,
        )
    )
    for s in result.scalars().all():
        s.status = SessionStatus.FAILED
        s.error = "Skipped due to earlier layer failures"
        s.finished_at = datetime.now(timezone.utc)
        await ws.publish(project_bus, {
            "type": "session_status",
            "session_id": s.session_id,
            "status": SessionStatus.FAILED,
            "error": s.error,
            "layer": s.layer,
        })
    await db.commit()
    await ws.publish(project_bus, {"type": "done"})


async def prepare_init_sessions(db, project_id: str, repos: list) -> list[dict]:
    """Compute and batch-create/reset init session records. Returns session defs.

    Idempotent: resets existing sessions, creates missing ones.
    Previously lived in the router layer; moved here for cleaner separation.
    """
    session_defs = compute_init_sessions(project_id, repos)
    for sd in session_defs:
        existing = await db.get(Session, sd["session_id"])
        if existing:
            existing.status = SessionStatus.WAITING
            existing.error = None
            existing.started_at = None
            existing.finished_at = None
            # Append run_boundary marker (preserves historical logs)
            await append_log(sd["session_id"], {
                "type": "run_boundary",
                "ts": utc_iso(datetime.now(timezone.utc)),
            })
        else:
            db.add(Session(**sd, status=SessionStatus.WAITING))
    await db.commit()
    return session_defs


async def get_init_layer_status(db, project_id: str) -> list[dict]:
    """Return per-layer aggregate status for project init sessions."""
    result = await db.execute(
        select(Session).where(
            Session.ref_id == project_id,
            Session.type == "init",
        ).order_by(Session.layer, Session.created_at)
    )
    sessions = result.scalars().all()

    layers: dict[int, dict] = {}
    for s in sessions:
        layer_num = s.layer or 0
        if layer_num not in layers:
            layers[layer_num] = {"layer": layer_num, "sessions": []}
        layers[layer_num]["sessions"].append({
            "session_id": s.session_id,
            "status": s.status,
            "error": s.error,
            "started_at": utc_iso(s.started_at) if s.started_at else None,
            "finished_at": utc_iso(s.finished_at) if s.finished_at else None,
        })

    for layer in layers.values():
        statuses = [sess["status"] for sess in layer["sessions"]]
        if all(st == SessionStatus.DONE for st in statuses):
            layer["status"] = "done"
        elif any(st == SessionStatus.FAILED for st in statuses):
            layer["status"] = "failed"
        elif any(st == SessionStatus.RUNNING for st in statuses):
            layer["status"] = "running"
        else:
            layer["status"] = "waiting"

    return sorted(layers.values(), key=lambda x: x["layer"])


async def run_init(project_id: str, ws_manager: WSManager | None = None):
    """Execute the 4-layer project knowledge generation pipeline.

    Uses an independent DB session for background execution.
    """
    ws = ws_manager or _default_ws_manager
    async with get_background_db() as db:
        project_dir = get_project_dir(project_id)
        project_bus = _init_bus(project_id)

        # Fetch repos
        result = await db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == project_id)
        )
        repos = result.scalars().all()

        # Layer 1: repo_clone
        async def _do_repo_clone(task_db, session_id):
            git_repos = [r for r in repos if r.git_url and not r.local_path]
            if not git_repos:
                await append_log(session_id, {
                    "type": "text_delta", "ts": utc_iso(datetime.now(timezone.utc)),
                    "content": "No remote repos to clone, skipping.\n",
                })
                return
            for r in git_repos:
                clone_dir = project_dir / "code" / repo_dir_name(r.git_url)
                await append_log(session_id, {
                    "type": "text_delta", "ts": utc_iso(datetime.now(timezone.utc)),
                    "content": f"Cloning/pulling {r.git_url} → {clone_dir} ...\n",
                })
                await clone_or_pull(r.git_url, str(clone_dir))
                # Seed master_hash for repo monitor
                try:
                    head = await get_head_hash(str(clone_dir))
                    await task_db.execute(
                        update(ProjectRepo).where(ProjectRepo.id == r.id).values(master_hash=head)
                    )
                except Exception:
                    pass
                await append_log(session_id, {
                    "type": "text_delta", "ts": utc_iso(datetime.now(timezone.utc)),
                    "content": f"✓ {repo_dir_name(r.git_url)} ready.\n",
                })

        layer1_results = await asyncio.gather(
            run_simple_task(_init_sid(project_id, "repo_clone"), project_bus, _do_repo_clone),
            return_exceptions=True,
        )
        for r in layer1_results:
            if isinstance(r, Exception):
                logger.error("Layer 1 task raised: %s", r)

        # Check if Layer 1 had critical failures (repo_clone failure = no code to analyze)
        layer1_sessions = await db.execute(
            select(Session).where(Session.ref_id == project_id, Session.layer == 1)
        )
        layer1_failed = [s for s in layer1_sessions.scalars().all() if s.status == SessionStatus.FAILED]
        if layer1_failed:
            failed_names = ", ".join(s.session_id for s in layer1_failed)
            logger.error("Layer 1 failed (%s), aborting init for project %s", failed_names, project_id)
            await ws.publish(project_bus, {"type": "done"})
            return

        # Resolve allowed_roots: git-cloned paths take priority over local_path
        allowed_roots = _resolve_allowed_roots(project_dir, repos)
        lang = await get_language_setting(db)

        # Layers 2 & 3: knowledge generation (concurrent within each layer, serial across)
        for layer_num in (2, 3):
            layer_sessions = await db.execute(
                select(Session).where(Session.ref_id == project_id, Session.layer == layer_num)
            )
            layer_ok = await _run_layer(
                layer_sessions.scalars().all(), layer_num,
                project_dir, allowed_roots, repos, project_bus, lang,
                project_id=project_id,
            )
            if not layer_ok:
                logger.error("Layer %d had failures, aborting init for project %s", layer_num, project_id)
                await _finalize_init(db, project_id, project_bus, ws)
                return

        # Layer 4: Generate project.md
        try:
            await _run_layer4(project_id, project_dir, allowed_roots, project_bus, lang)
        except Exception as e:
            logger.error("Layer 4 project.md generation failed: %s", e)

        # Layer 5: Generate constitution.md
        try:
            await _run_constitution(project_id, project_dir, allowed_roots, project_bus, lang)
        except Exception as e:
            logger.error("Layer 5 constitution.md generation failed: %s", e)

        await _finalize_init(db, project_id, project_bus, ws)


async def run_init_retry(project_id: str, failed_session_ids: list[str], from_layer: int):
    """Re-run failed sessions in from_layer + all sessions in subsequent layers."""
    async with get_background_db() as db:
        project_dir = get_project_dir(project_id)
        project_bus = _init_bus(project_id)

        # Fetch repos and resolve allowed_roots (use cloned paths if available)
        result = await db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == project_id)
        )
        repos = result.scalars().all()
        allowed_roots = _resolve_allowed_roots(project_dir, repos)

        lang = await get_language_setting(db)

        # Run failed sessions in from_layer
        if from_layer == 4:
            try:
                await _run_layer4(project_id, project_dir, allowed_roots, project_bus, lang)
            except Exception as e:
                logger.error("Retry layer 4 project.md failed: %s", e)
                await _finalize_init(db, project_id, project_bus)
                return
        elif from_layer == 5:
            try:
                await _run_constitution(project_id, project_dir, allowed_roots, project_bus, lang)
            except Exception as e:
                logger.error("Retry layer 5 constitution.md failed: %s", e)
            await _finalize_init(db, project_id, project_bus)
            return
        else:
            failed_results = await db.execute(
                select(Session).where(Session.session_id.in_(failed_session_ids))
            )
            failed_sessions = failed_results.scalars().all()
            if failed_sessions:
                layer_ok = await _run_layer(failed_sessions, from_layer, project_dir, allowed_roots, repos, project_bus, lang,
                                            project_id=project_id)
                if not layer_ok:
                    logger.error("Retry layer %d had failures, aborting init for project %s", from_layer, project_id)
                    await _finalize_init(db, project_id, project_bus)
                    return

        # Run all sessions in subsequent layers
        for layer_num in range(from_layer + 1, 6):  # layers go up to 5
            if layer_num == 4:
                try:
                    await _run_layer4(project_id, project_dir, allowed_roots, project_bus, lang)
                except Exception as e:
                    logger.error("Retry layer 4 project.md failed: %s", e)
            elif layer_num == 5:
                try:
                    await _run_constitution(project_id, project_dir, allowed_roots, project_bus, lang)
                except Exception as e:
                    logger.error("Retry layer 5 constitution.md failed: %s", e)
            else:
                layer_results = await db.execute(
                    select(Session).where(
                        Session.ref_id == project_id, Session.layer == layer_num
                    )
                )
                layer_sessions = layer_results.scalars().all()
                layer_ok = await _run_layer(layer_sessions, layer_num, project_dir, allowed_roots, repos, project_bus, lang,
                                            project_id=project_id)
                if not layer_ok:
                    logger.error("Retry layer %d had failures, aborting init for project %s", layer_num, project_id)
                    await _finalize_init(db, project_id, project_bus)
                    return

        await _finalize_init(db, project_id, project_bus)
