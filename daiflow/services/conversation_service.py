"""Conversation lifecycle: create, init (copy code + sync skills), delete."""

import logging
import shutil
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import get_conversation_dir, get_conversation_skills_dir, get_project_dir, utc_iso
from daiflow.database import get_background_db
from daiflow.models import Conversation, ConversationStatus, Project, Session, SessionStatus
from daiflow.services.project_service import repo_dir_name
from daiflow.services.task_service import fetch_project_repos, resolve_repo_path_in
from daiflow.session_ids import conversation_init_bus, conversation_init_fetch, conversation_init_skills
from daiflow.ws_manager import WSManager, ws_manager as _default_ws_manager

logger = logging.getLogger(__name__)


def _copy_code_to_conversation(project_id: str, conv_id: str, repos: list):
    """Copy cloned code from project/code/ to conversation/code/ for git-only repos.

    After copying, removes .git directories to prevent accidental pushes.
    Conversation code is read-only context — not a real git working tree.
    """
    project_dir = get_project_dir(project_id)
    conv_dir = get_conversation_dir(conv_id)

    for r in repos:
        if r.git_url and not r.local_path:
            repo_name = repo_dir_name(r.git_url)
            src = project_dir / "code" / repo_name
            dst = conv_dir / "code" / repo_name
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                # Remove .git to prevent accidental pushes from conversation context
                git_dir = dst / ".git"
                if git_dir.exists():
                    shutil.rmtree(git_dir)
                logger.info("Copied code %s -> %s (git removed)", src, dst)


def resolve_conversation_roots(conv_id: str, repos: list) -> list[str]:
    """Resolve allowed_roots for a conversation."""
    return resolve_repo_path_in(get_conversation_dir(conv_id), repos)


async def get_conversation_context(db: AsyncSession, conv_id: str, project_id: str) -> tuple[list, list[str]]:
    """Fetch repos and resolve allowed_roots for a conversation."""
    repos = await fetch_project_repos(db, project_id)
    allowed_roots = resolve_conversation_roots(conv_id, repos)
    return repos, allowed_roots


async def _do_fetch_code(db: AsyncSession, session_id: str, *, conv_id: str, project_id: str):
    """Subtask: copy code repos to conversation directory."""
    from daiflow.session_runner import append_log

    repos = await fetch_project_repos(db, project_id)
    _copy_code_to_conversation(project_id, conv_id, repos)

    now_iso = lambda: utc_iso(datetime.now(timezone.utc))
    await append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"Copied {len(repos)} repo(s) to conversation directory\n"})


async def _do_sync_skills(db: AsyncSession, session_id: str, *, conv_id: str, project_id: str):
    """Subtask: sync project skills to conversation directory."""
    from daiflow.session_runner import append_log
    from daiflow.services.skill_service import sync_skills_to_dir

    count = await sync_skills_to_dir(db, project_id, get_conversation_skills_dir(conv_id))
    await append_log(session_id, {"type": "text_delta", "ts": utc_iso(datetime.now(timezone.utc)), "content": f"✓ Synced {count} skill(s) to conversation\n"})


async def init_conversation(conv_id: str, ws_manager: WSManager | None = None):
    """Initialize a conversation: fetch code + sync skills, then mark READY."""
    from daiflow.workflow.pipeline import run_simple_task

    ws = ws_manager or _default_ws_manager
    init_bus = conversation_init_bus(conv_id)

    try:
        async with get_background_db() as db:
            conv = await db.get(Conversation, conv_id)
            if not conv:
                return

            project = await db.get(Project, conv.project_id)
            if not project:
                return

            conv.status = ConversationStatus.CREATING
            await db.commit()

            # Create session records for init subtasks
            fetch_sid = conversation_init_fetch(conv_id)
            skills_sid = conversation_init_skills(conv_id)
            for sid in (fetch_sid, skills_sid):
                existing = await db.get(Session, sid)
                if not existing:
                    db.add(Session(session_id=sid, type="conversation_init", ref_id=conv_id, status=SessionStatus.WAITING))
            await db.commit()

            project_id = conv.project_id

        # Run subtasks sequentially
        await run_simple_task(
            fetch_sid, init_bus,
            lambda db, sid: _do_fetch_code(db, sid, conv_id=conv_id, project_id=project_id),
        )
        await run_simple_task(
            skills_sid, init_bus,
            lambda db, sid: _do_sync_skills(db, sid, conv_id=conv_id, project_id=project_id),
        )

        # Mark as READY
        async with get_background_db() as db:
            conv = await db.get(Conversation, conv_id)
            if conv:
                conv.status = ConversationStatus.READY
                await db.commit()

        await ws.publish(init_bus, {"type": "done"})

    except Exception:
        logger.exception("init_conversation failed for %s", conv_id)
        await ws.publish(init_bus, {"type": "done"})
        try:
            async with get_background_db() as db:
                conv = await db.get(Conversation, conv_id)
                if conv and conv.status == ConversationStatus.CREATING:
                    conv.status = ConversationStatus.FAILED
                    await db.commit()
        except Exception:
            logger.exception("Failed to mark conversation %s as failed", conv_id)


def delete_conversation_dir(conv_id: str):
    """Remove conversation working directory."""
    from daiflow.config import CONVERSATIONS_DIR
    conv_dir = CONVERSATIONS_DIR / conv_id
    if conv_dir.exists():
        shutil.rmtree(conv_dir)
