import json
import logging
import shutil
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_background_db
from daiflow.exceptions import InvalidStateError
from daiflow.models import Project, ProjectRepo, Session, SessionStatus, Task, TaskStatus, Todo, TodoStatus
from daiflow.services.git_service import checkout_branch, get_head_hash
from daiflow.services.project_service import repo_dir_name
from daiflow.config import get_project_dir, get_task_dir
from daiflow.workflow import TaskWorkflow, TodoWorkflow
from daiflow.session_ids import (
    task_init_bus,
    task_init_fetch,
    task_init_skills,
    task_plan,
    task_spec,
    task_todo_exec,
    task_todo_split,
)
from daiflow.ws_manager import WSManager, ws_manager as _default_ws_manager

logger = logging.getLogger(__name__)

# In-memory set tracking tasks currently under run-all execution.
# Cleared on server restart (correct: the loop is also gone after restart).
_running_all_tasks: set[str] = set()
_cancel_run_all_tasks: set[str] = set()


def is_running_all(task_id: str) -> bool:
    """Return True if a run-all-todos loop is currently active for this task."""
    return task_id in _running_all_tasks


def cancel_running_all(task_id: str) -> bool:
    """Request cancellation of a run-all loop. Returns True if was running."""
    if task_id not in _running_all_tasks:
        return False
    _cancel_run_all_tasks.add(task_id)
    return True


async def fetch_project_repos(db: AsyncSession, project_id: str) -> list:
    """Fetch all ProjectRepo records for a project. Shared by services and routers."""
    result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == project_id)
    )
    return result.scalars().all()


def _copy_code_to_task(project_id: str, task_id: str, repos: list):
    """Copy cloned code from project/code/ to task/code/ for git-only repos.

    Only copies repos that have git_url but no local_path.
    Repos with local_path are used in-place (user's working directory).
    """
    project_dir = get_project_dir(project_id)
    task_dir = get_task_dir(task_id)

    for r in repos:
        if r.git_url and not r.local_path:
            repo_name = repo_dir_name(r.git_url)
            src = project_dir / "code" / repo_name
            dst = task_dir / "code" / repo_name
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                logger.info("Copied code %s -> %s", src, dst)


def resolve_repo_path_in(base_dir, repos: list) -> list[str]:
    """Resolve filesystem paths for repos under a base directory.

    Shared logic used by both project init (project dir) and task execution (task dir).

    - Repos with local_path: use local_path directly (user's working directory)
    - Git-only repos: use base_dir/code/{repo_name} (isolated copy)
    """
    roots = []
    for r in repos:
        if r.local_path:
            roots.append(r.local_path)
        elif r.git_url:
            roots.append(str(base_dir / "code" / repo_dir_name(r.git_url)))
    return roots


def resolve_repo_path(repo, task_id: str) -> str | None:
    """Resolve the actual filesystem path for a single repo in a task context."""
    if repo.local_path:
        return repo.local_path
    elif repo.git_url:
        return str(get_task_dir(task_id) / "code" / repo_dir_name(repo.git_url))
    return None


def resolve_task_roots(task_id: str, repos: list) -> list[str]:
    """Resolve allowed_roots for a task."""
    return resolve_repo_path_in(get_task_dir(task_id), repos)


async def get_task_context(db: AsyncSession, task_id: str, project_id: str) -> tuple[list, list[str]]:
    """Fetch repos and resolve allowed_roots for a task. Common pattern used by multiple services.

    Returns:
        (repos, allowed_roots) tuple.
    """
    repos = await fetch_project_repos(db, project_id)
    allowed_roots = resolve_task_roots(task_id, repos)
    return repos, allowed_roots



async def _do_fetch_code(db: AsyncSession, session_id: str, *, task_id: str, project_id: str, branch: str | None):
    """Subtask: copy code repos and checkout branch."""
    from daiflow.session_runner import append_log

    repos = await fetch_project_repos(db, project_id)
    _copy_code_to_task(project_id, task_id, repos)

    from daiflow.config import utc_iso
    now_iso = lambda: utc_iso(datetime.now(timezone.utc))
    await append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"Copied {len(repos)} repo(s) to task directory\n"})

    if branch:
        for repo in repos:
            repo_path = resolve_repo_path(repo, task_id)
            if not repo_path:
                continue
            label = repo.local_path or repo_dir_name(repo.git_url)
            try:
                await checkout_branch(repo_path, branch)
                await append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"✓ Checked out branch '{branch}' on {label}\n"})
            except Exception as e:
                logger.warning("Branch checkout for %s on %s: %s", branch, repo_path, e)
                await append_log(session_id, {"type": "text_delta", "ts": now_iso(), "content": f"⚠ Branch checkout failed on {label}: {e}\n"})


async def _do_sync_skills(db: AsyncSession, session_id: str, *, task_id: str, project_id: str):
    """Subtask: sync project skills to task directory (DB-backed with legacy fallback)."""
    from daiflow.session_runner import append_log
    from daiflow.services.skill_sync import sync_skills_to_task

    count = await sync_skills_to_task(db, project_id, task_id)
    from daiflow.config import utc_iso
    await append_log(session_id, {"type": "text_delta", "ts": utc_iso(datetime.now(timezone.utc)), "content": f"✓ Synced {count} skill(s) to task\n"})


async def init_task(task_id: str, ws_manager: WSManager | None = None):
    """Initialize a task: fetch code + sync skills, then wait for user confirmation.

    Creates Session records for each subtask so the frontend can show progress.
    Does NOT auto-trigger plan generation — user must confirm via /confirm-init.
    """
    from daiflow.workflow.pipeline import run_simple_task

    ws = ws_manager or _default_ws_manager
    init_bus = task_init_bus(task_id)

    try:
        async with get_background_db() as db:
            task = await db.get(Task, task_id)
            if not task:
                return

            project = await db.get(Project, task.project_id)
            if not project:
                return

            # Transition: created → initializing
            wf = TaskWorkflow(task, db)
            await wf.initialize()

            # Create session records for init subtasks
            fetch_sid = task_init_fetch(task_id)
            skills_sid = task_init_skills(task_id)
            for sid in (fetch_sid, skills_sid):
                existing = await db.get(Session, sid)
                if not existing:
                    db.add(Session(session_id=sid, type="task_init", ref_id=task_id, task_id=task_id, status=SessionStatus.WAITING))
            await db.commit()

        # Run subtasks sequentially
        await run_simple_task(
            fetch_sid, init_bus,
            lambda db, sid: _do_fetch_code(db, sid, task_id=task_id, project_id=task.project_id, branch=task.branch),
        )
        await run_simple_task(
            skills_sid, init_bus,
            lambda db, sid: _do_sync_skills(db, sid, task_id=task_id, project_id=task.project_id),
        )

        # Publish init done event
        await ws.publish(init_bus, {"type": "done"})

    except Exception:
        logger.exception("init_task failed for task %s", task_id)
        # Notify frontend that init is done (with failures)
        await ws.publish(init_bus, {"type": "done"})
        # Reset to CREATED so user can retry
        try:
            async with get_background_db() as db:
                task = await db.get(Task, task_id)
                if task and task.status == TaskStatus.INITIALIZING:
                    wf = TaskWorkflow(task, db)
                    await wf.reset_init()
                    await db.commit()
        except Exception:
            logger.exception("Failed to reset task %s status after init failure", task_id)


async def generate_plan(task_id: str):
    """Generate technical plan for a task.

    Uses an independent DB session for background execution.
    Delegates to AgentExecutor with the "plan" agent config.
    """
    from daiflow.agent_executor import run_agent

    async with get_background_db() as db:
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before plan generation started", task_id)
            return

        session_id = task_plan(task_id)
        await run_agent(db, "plan", entity_id=task_id, session_id=session_id)


async def generate_spec(task_id: str):
    """Generate functional specification (spec.md) for a task.

    Task must be in PLANNING state.
    """
    from daiflow.agent_executor import run_agent

    async with get_background_db() as db:
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before spec generation started", task_id)
            return

        session_id = task_spec(task_id)
        await run_agent(db, "spec", entity_id=task_id, session_id=session_id)
    # Auto-trigger plan generation after spec completes (success or failure)
    await generate_plan(task_id)


async def generate_todos(task_id: str):
    """Generate todo decomposition from the plan.

    Reuses the plan's Cody session for context continuity.
    Delegates to AgentExecutor with the "todo_split" agent config.
    """
    from daiflow.agent_executor import run_agent

    async with get_background_db() as db:
        task = await db.get(Task, task_id)
        if not task:
            logger.debug("Task %s deleted before todo generation started", task_id)
            return

        session_id = task_todo_split(task_id)
        await run_agent(db, "todo_split", entity_id=task_id, session_id=session_id)


async def sync_todos_from_file(db: AsyncSession, task_id: str, content: str):
    """Parse todo.json content and sync to database.

    Deletes existing todos and re-creates them from the file content.
    Used by todo/chat to keep DB in sync after AI edits todo.json.
    """
    try:
        todos_data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to parse todo.json content for task %s: %s", task_id, e)
        raise InvalidStateError(f"Invalid todo.json format: {e}") from e

    # Delete only pending todos — preserve running/done/failed
    _preserve_statuses = (TodoStatus.RUNNING, TodoStatus.DONE, TodoStatus.FAILED, TodoStatus.SKIPPED)
    result = await db.execute(
        select(Todo).where(Todo.task_id == task_id)
    )
    existing = result.scalars().all()
    preserved = {t.seq: t for t in existing if t.status in _preserve_statuses}
    for t in existing:
        if t.status not in _preserve_statuses:
            await db.delete(t)

    # Insert new todos, skipping sequences that are preserved (running/done)
    for item in todos_data:
        seq = item.get("seq", 0)
        if seq in preserved:
            continue
        todo = Todo(
            task_id=task_id,
            seq=seq,
            title=item.get("title", ""),
            description=item.get("description", ""),
        )
        db.add(todo)
    await db.commit()


def _parse_todos_json(content: str) -> list[dict]:
    """Parse todo.json content into a list of todo dicts. Raises on invalid JSON."""
    data = json.loads(content)
    return [
        {"seq": item.get("seq", 0), "title": item.get("title", ""), "description": item.get("description", "")}
        for item in data
    ]


def _insert_todos(db: AsyncSession, task_id: str, todos_data: list[dict]):
    """Add parsed todo items to the DB session.

    Note: This only calls db.add() (synchronous on AsyncSession).
    The caller MUST await db.commit() to persist the changes.
    """
    for item in todos_data:
        db.add(Todo(task_id=task_id, seq=item["seq"], title=item["title"], description=item["description"]))


async def start_coding(task_id: str, db: AsyncSession):
    """Parse todo.json (if not already parsed), update task status to coding.

    Status transition is handled by TaskWorkflow in the router layer.
    This function only ensures todos are loaded into DB.
    """
    task = await db.get(Task, task_id)
    if not task:
        return

    # Check if todos already exist (from generate_todos)
    result = await db.execute(
        select(Todo).where(Todo.task_id == task_id)
    )
    existing_todos = result.scalars().all()

    if not existing_todos:
        # Fallback: parse todo.json if generate_todos didn't do it
        task_dir = get_task_dir(task_id)
        todo_path = task_dir / "todo.json"

        if todo_path.exists():
            try:
                _insert_todos(db, task_id, _parse_todos_json(todo_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error("Failed to parse todo.json for task %s: %s", task_id, e)

    await db.commit()


async def execute_todo(todo_id: str):
    """Execute a single todo item.

    The router has already transitioned the todo to RUNNING.
    This function runs Cody and transitions to done/failed.
    Delegates to AgentExecutor with the "todo_exec" agent config.
    """
    from daiflow.agent_executor import run_agent

    async with get_background_db() as db:
        todo = await db.get(Todo, todo_id)
        if not todo:
            return

        task = await db.get(Task, todo.task_id)
        if not task:
            return

        _, allowed_roots = await get_task_context(db, task.id, task.project_id)

        # Record HEAD hash of each repo before execution
        head_before: dict[str, str] = {}
        for root in allowed_roots:
            try:
                head_before[root] = await get_head_hash(root)
            except Exception:
                pass
        todo.commit_before = json.dumps(head_before)
        await db.commit()

        session_id = task_todo_exec(task.id, todo_id)
        await run_agent(db, "todo_exec", entity_id=todo_id, session_id=session_id, task_id=task.id)


async def run_all_todos(task_id: str) -> None:
    """Execute all PENDING/FAILED todos sequentially in the background.

    Tracks execution in the module-level _running_all_tasks set.
    Cleared automatically on normal completion, error, or server restart.
    """
    from transitions.core import MachineError

    _running_all_tasks.add(task_id)
    _cancel_run_all_tasks.discard(task_id)
    try:
        while True:
            # Check for cancellation between todo executions
            if task_id in _cancel_run_all_tasks:
                logger.info("run_all_todos: cancelled by user for task %s", task_id)
                break
            todo_id: str | None = None
            async with get_background_db() as db:
                task = await db.get(Task, task_id)
                if not task or task.status != TaskStatus.CODING:
                    break
                result = await db.execute(
                    select(Todo)
                    .where(Todo.task_id == task_id)
                    .order_by(Todo.seq)
                )
                todos = result.scalars().all()
                next_todo = next(
                    (t for t in todos if t.status in (TodoStatus.PENDING, TodoStatus.FAILED)),
                    None,
                )
                if not next_todo:
                    break
                wf = TodoWorkflow(next_todo, db)
                try:
                    if next_todo.status == TodoStatus.FAILED:
                        ok = await wf.retry()
                    else:
                        ok = await wf.execute()
                except MachineError:
                    logger.warning("run_all_todos: MachineError on todo %s, stopping", next_todo.id)
                    break
                if not ok:
                    logger.warning("run_all_todos: execute guard failed for todo %s, stopping", next_todo.id)
                    break
                await db.commit()
                todo_id = next_todo.id
            if not todo_id:
                break
            # Run outside the db context so the session is released before Cody execution
            await execute_todo(todo_id)
    except Exception:
        logger.exception("run_all_todos failed for task %s", task_id)
    finally:
        _running_all_tasks.discard(task_id)
        _cancel_run_all_tasks.discard(task_id)
