import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import SESSIONS_DIR, safe_filename
from daiflow.database import get_db
from daiflow.models import Session, SessionStatus, Task, TaskStatus, Todo, TodoStatus
from daiflow.schemas import SessionStatusResponse
from transitions.core import MachineError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/running")
async def get_running_sessions(db: AsyncSession = Depends(get_db)):
    """Return count of currently running sessions (for desktop close protection)."""
    result = await db.execute(
        select(func.count()).select_from(Session).where(
            Session.status == SessionStatus.RUNNING
        )
    )
    return {"count": result.scalar()}


@router.get("")
async def list_sessions(
    ref_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List sessions with optional filters. For the debug/troubleshoot page."""
    query = select(Session).order_by(Session.created_at.desc())
    if ref_id:
        query = query.where(Session.ref_id == ref_id)
    if type:
        query = query.where(Session.type == type)
    result = await db.execute(query.limit(200))
    sessions = result.scalars().all()
    return [
        SessionStatusResponse.model_validate(s).model_dump()
        for s in sessions
    ]


@router.get("/{session_id:path}/status")
async def get_session_status(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionStatusResponse.model_validate(session).model_dump()


async def _sync_associated_entity(session: Session, db: AsyncSession) -> list[str]:
    """Propagate a FAILED session's status to its associated entity via state machine.

    Returns a list of human-readable change descriptions.

    Mapping:
    - todo_exec → Todo: RUNNING → FAILED (via TodoWorkflow.fail)
    - plan → Task: stays in PLANNING (via TaskWorkflow.reset_plan)
    - todo_split → Task: PLAN_LOCKED → PLANNING (via TaskWorkflow.reset_todos)
    - review → Task: REVIEWING → CODING (via TaskWorkflow.reset_review)
    """
    from daiflow.workflow.task_machine import TaskWorkflow
    from daiflow.workflow.todo_machine import TodoWorkflow

    changes: list[str] = []

    if session.type == "todo_exec":
        parts = session.session_id.split(":")
        if len(parts) >= 4:
            todo_id = parts[-1]
            todo = await db.get(Todo, todo_id)
            if todo and todo.status not in (TodoStatus.FAILED, TodoStatus.DONE):
                old = TodoStatus(todo.status).name
                try:
                    wf = TodoWorkflow(todo, db)
                    await wf.fail()
                    changes.append(f"Todo: {old} → FAILED")
                except (Exception, MachineError):
                    # Fallback if state machine rejects (e.g. not in RUNNING).
                    # Direct assignment is intentional here as a last-resort recovery
                    # when the state machine cannot handle the current state.
                    todo.status = TodoStatus.FAILED  # noqa: direct-status (recovery fallback)
                    changes.append(f"Todo: {old} → FAILED (forced)")

    elif session.type == "plan" and session.task_id:
        task = await db.get(Task, session.task_id)
        if task and task.status == TaskStatus.PLANNING:
            wf = TaskWorkflow(task, db)
            await wf.reset_plan()
            changes.append("Task: PLANNING → PLANNING (ready for retry)")

    elif session.type == "todo_split" and session.task_id:
        task = await db.get(Task, session.task_id)
        if task and task.status == TaskStatus.PLAN_LOCKED:
            wf = TaskWorkflow(task, db)
            await wf.reset_todos()
            changes.append("Task: PLAN_LOCKED → PLANNING")

    elif session.type == "review" and session.task_id:
        task = await db.get(Task, session.task_id)
        if task and task.status == TaskStatus.REVIEWING:
            wf = TaskWorkflow(task, db)
            await wf.reset_review()
            changes.append("Task: REVIEWING → CODING")

    return changes


@router.post("/{session_id:path}/force-fail")
async def force_fail_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Manually mark a WAITING/RUNNING session as FAILED and sync associated entity."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status not in (SessionStatus.WAITING, SessionStatus.RUNNING):
        raise HTTPException(
            status_code=400,
            detail=f"Session is already in terminal state: {SessionStatus(session.status).name}",
        )

    now = datetime.now(timezone.utc)
    session.status = SessionStatus.FAILED
    session.error = "Manually marked as failed from debug page"
    session.finished_at = now

    changes = await _sync_associated_entity(session, db)
    await db.commit()

    if changes:
        logger.info("Force-failed session %s, synced: %s", session_id, "; ".join(changes))
    return SessionStatusResponse.model_validate(session).model_dump()


@router.post("/{session_id:path}/sync-status")
async def sync_associated_status(session_id: str, db: AsyncSession = Depends(get_db)):
    """Fix orphaned entities: propagate an already-FAILED session to its associated entity."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != SessionStatus.FAILED:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not failed (status={SessionStatus(session.status).name}), nothing to sync",
        )

    changes = await _sync_associated_entity(session, db)
    await db.commit()

    msg = "; ".join(changes) if changes else "Already in sync, no changes needed"
    logger.info("Synced status for session %s: %s", session_id, msg)
    return {"message": msg}


def _read_logs_sync(log_path, limit: int, offset: int, all_attempts: bool) -> list:
    """Read JSONL logs from disk (sync, runs in thread pool).

    By default, returns only logs from the latest run attempt
    (everything after the last run_boundary marker). Set all_attempts=True
    to return the full log history across all attempts.
    """
    all_logs: list[tuple[int, dict]] = []  # (index, parsed_event)
    last_boundary = -1
    idx = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            all_logs.append((idx, event))
            if event.get("type") == "run_boundary":
                last_boundary = idx
            idx += 1

    # Filter to latest attempt unless all_attempts requested
    if not all_attempts and last_boundary >= 0:
        logs = [ev for (i, ev) in all_logs if i > last_boundary]
    else:
        logs = [ev for (_, ev) in all_logs]

    # Apply offset + limit
    return logs[offset : offset + limit]


@router.get("/{session_id:path}/logs")
async def get_session_logs(
    session_id: str,
    limit: int = 5000,
    offset: int = 0,
    all_attempts: bool = False,
):
    log_path = SESSIONS_DIR / f"{safe_filename(session_id)}.jsonl"
    if not log_path.exists():
        return []
    return await asyncio.to_thread(_read_logs_sync, log_path, limit, offset, all_attempts)
