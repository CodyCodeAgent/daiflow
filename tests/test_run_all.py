"""Tests for run-all-todos and cancel-run-all functionality."""

import pytest

from daiflow.models import Project, Task, TaskStatus, Todo, TodoStatus
from daiflow.services.task_service import (
    _running_all_tasks,
    _cancel_run_all_tasks,
    cancel_running_all,
    is_running_all,
)


# ── Unit tests for in-memory cancel state ──


def test_is_running_all_false_by_default():
    """is_running_all returns False for unknown task."""
    assert is_running_all("nonexistent") is False


def test_cancel_running_all_returns_false_when_not_running():
    """cancel_running_all returns False if task is not in run-all loop."""
    assert cancel_running_all("nonexistent") is False


def test_cancel_running_all_returns_true_when_running():
    """cancel_running_all returns True and sets cancel flag when running."""
    task_id = "test_cancel_task"
    _running_all_tasks.add(task_id)
    try:
        assert is_running_all(task_id) is True
        assert cancel_running_all(task_id) is True
        assert task_id in _cancel_run_all_tasks
    finally:
        _running_all_tasks.discard(task_id)
        _cancel_run_all_tasks.discard(task_id)


def test_cancel_running_all_idempotent():
    """Calling cancel_running_all multiple times is safe."""
    task_id = "test_idempotent"
    _running_all_tasks.add(task_id)
    try:
        assert cancel_running_all(task_id) is True
        assert cancel_running_all(task_id) is True  # second call still True
    finally:
        _running_all_tasks.discard(task_id)
        _cancel_run_all_tasks.discard(task_id)


# ── API route tests ──


@pytest.fixture
async def task_in_coding(client, db_engine):
    """Create a project + task in CODING status with some todos."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        project = Project(id="proj_run_all", name="Test Project")
        db.add(project)
        await db.flush()

        task = Task(
            id="task_run_all",
            name="Run All Test",
            project_id="proj_run_all",
            status=TaskStatus.CODING,
            branch="feature/test",
        )
        db.add(task)
        await db.flush()

        for i in range(3):
            todo = Todo(
                id=f"todo_ra_{i}",
                task_id="task_run_all",
                seq=i + 1,
                title=f"Todo {i + 1}",
                status=TodoStatus.PENDING,
            )
            db.add(todo)

        await db.commit()
    return "task_run_all"


async def test_cancel_run_all_route_no_run_in_progress(client):
    """POST /cancel-run-all returns 400 when nothing is running."""
    resp = await client.post("/api/tasks/nonexistent/cancel-run-all")
    assert resp.status_code == 400
    assert "No run-all in progress" in resp.json()["detail"]


async def test_cancel_run_all_route_success(client, task_in_coding):
    """POST /cancel-run-all returns ok when run-all is in progress."""
    task_id = task_in_coding
    _running_all_tasks.add(task_id)
    try:
        resp = await client.post(f"/api/tasks/{task_id}/cancel-run-all")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert task_id in _cancel_run_all_tasks
    finally:
        _running_all_tasks.discard(task_id)
        _cancel_run_all_tasks.discard(task_id)
