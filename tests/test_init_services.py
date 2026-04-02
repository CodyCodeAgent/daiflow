"""Tests for init session services and startup recovery logic."""

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from daiflow.models import (
    Project,
    ProjectRepo,
    Session,
    SessionStatus,
    Todo,
    TodoStatus,
)
from daiflow.services.project_service import (
    compute_init_sessions,
    prepare_init_sessions,
    get_init_layer_status,
)


# ── prepare_init_sessions Tests ──


class TestPrepareInitSessions:
    async def test_creates_new_sessions(self, db_session):
        """Should create all session records for a project init."""
        repos = [SimpleNamespace(repo_type="frontend")]
        session_defs = await prepare_init_sessions(db_session, "proj_1", repos)

        assert len(session_defs) > 0
        # Verify all sessions exist in DB
        for sd in session_defs:
            session = await db_session.get(Session, sd["session_id"])
            assert session is not None
            assert session.status == SessionStatus.WAITING
            assert session.type == "init"
            assert session.ref_id == "proj_1"

    async def test_resets_existing_sessions(self, db_session):
        """Re-init should reset existing sessions to WAITING."""
        repos = [SimpleNamespace(repo_type="backend")]
        session_defs = compute_init_sessions("proj_2", repos)

        # Pre-create a DONE session
        first_sid = session_defs[0]["session_id"]
        db_session.add(Session(
            session_id=first_sid,
            type="init",
            ref_id="proj_2",
            status=SessionStatus.DONE,
            error="old error",
        ))
        await db_session.commit()

        with patch("daiflow.services.project_service.append_log", new_callable=AsyncMock) as mock_log:
            result = await prepare_init_sessions(db_session, "proj_2", repos)

        # Session should be reset
        session = await db_session.get(Session, first_sid)
        assert session.status == SessionStatus.WAITING
        assert session.error is None

        # run_boundary should have been appended for the existing session
        mock_log.assert_called()
        boundary_calls = [c for c in mock_log.call_args_list
                         if c[0][1].get("type") == "run_boundary"]
        assert len(boundary_calls) >= 1

    async def test_idempotent(self, db_session):
        """Calling twice should not duplicate sessions."""
        repos = [SimpleNamespace(repo_type="frontend")]

        with patch("daiflow.services.project_service.append_log", new_callable=AsyncMock):
            first = await prepare_init_sessions(db_session, "proj_3", repos)
            second = await prepare_init_sessions(db_session, "proj_3", repos)

        assert len(first) == len(second)
        # All session IDs should be the same
        first_ids = {s["session_id"] for s in first}
        second_ids = {s["session_id"] for s in second}
        assert first_ids == second_ids

    async def test_returns_session_defs(self, db_session):
        """Should return the computed session definitions."""
        repos = [SimpleNamespace(repo_type="frontend")]
        result = await prepare_init_sessions(db_session, "proj_4", repos)

        assert isinstance(result, list)
        for sd in result:
            assert "session_id" in sd
            assert "type" in sd
            assert "layer" in sd
            assert "ref_id" in sd


# ── get_init_layer_status Tests ──


class TestGetInitLayerStatus:
    async def test_empty_project(self, db_session):
        """No sessions → empty list."""
        result = await get_init_layer_status(db_session, "nonexistent")
        assert result == []

    async def test_all_waiting(self, db_session):
        """All WAITING sessions → layer status is 'waiting'."""
        sessions = [
            Session(session_id="init:p1:skill_fetch", type="init", ref_id="p1", layer=1, status=SessionStatus.WAITING),
            Session(session_id="init:p1:repo_clone", type="init", ref_id="p1", layer=1, status=SessionStatus.WAITING),
        ]
        db_session.add_all(sessions)
        await db_session.commit()

        result = await get_init_layer_status(db_session, "p1")
        assert len(result) == 1
        assert result[0]["layer"] == 1
        assert result[0]["status"] == "waiting"
        assert len(result[0]["sessions"]) == 2

    async def test_all_done(self, db_session):
        db_session.add_all([
            Session(session_id="init:p2:skill_fetch", type="init", ref_id="p2", layer=1, status=SessionStatus.DONE),
            Session(session_id="init:p2:repo_clone", type="init", ref_id="p2", layer=1, status=SessionStatus.DONE),
        ])
        await db_session.commit()

        result = await get_init_layer_status(db_session, "p2")
        assert result[0]["status"] == "done"

    async def test_any_failed(self, db_session):
        db_session.add_all([
            Session(session_id="init:p3:skill_fetch", type="init", ref_id="p3", layer=1, status=SessionStatus.DONE),
            Session(session_id="init:p3:repo_clone", type="init", ref_id="p3", layer=1, status=SessionStatus.FAILED, error="git error"),
        ])
        await db_session.commit()

        result = await get_init_layer_status(db_session, "p3")
        assert result[0]["status"] == "failed"

    async def test_any_running(self, db_session):
        db_session.add_all([
            Session(session_id="init:p4:skill_fetch", type="init", ref_id="p4", layer=1, status=SessionStatus.DONE),
            Session(session_id="init:p4:repo_clone", type="init", ref_id="p4", layer=1, status=SessionStatus.RUNNING),
        ])
        await db_session.commit()

        result = await get_init_layer_status(db_session, "p4")
        assert result[0]["status"] == "running"

    async def test_failed_takes_priority_over_running(self, db_session):
        """If any session failed, layer is 'failed' even if others are running."""
        db_session.add_all([
            Session(session_id="init:p5:a", type="init", ref_id="p5", layer=1, status=SessionStatus.RUNNING),
            Session(session_id="init:p5:b", type="init", ref_id="p5", layer=1, status=SessionStatus.FAILED),
        ])
        await db_session.commit()

        result = await get_init_layer_status(db_session, "p5")
        assert result[0]["status"] == "failed"

    async def test_multiple_layers(self, db_session):
        db_session.add_all([
            Session(session_id="init:p6:skill_fetch", type="init", ref_id="p6", layer=1, status=SessionStatus.DONE),
            Session(session_id="init:p6:repo_clone", type="init", ref_id="p6", layer=1, status=SessionStatus.DONE),
            Session(session_id="init:p6:frontend-structure", type="init", ref_id="p6", layer=2, status=SessionStatus.RUNNING),
            Session(session_id="init:p6:module-overview", type="init", ref_id="p6", layer=3, status=SessionStatus.WAITING),
        ])
        await db_session.commit()

        result = await get_init_layer_status(db_session, "p6")
        assert len(result) == 3
        # Should be sorted by layer
        assert result[0]["layer"] == 1
        assert result[0]["status"] == "done"
        assert result[1]["layer"] == 2
        assert result[1]["status"] == "running"
        assert result[2]["layer"] == 3
        assert result[2]["status"] == "waiting"

    async def test_session_details(self, db_session):
        """Each session entry should have the expected fields."""
        now = datetime.now(timezone.utc)
        db_session.add(Session(
            session_id="init:p7:skill_fetch",
            type="init",
            ref_id="p7",
            layer=1,
            status=SessionStatus.DONE,
            started_at=now,
            finished_at=now,
        ))
        await db_session.commit()

        result = await get_init_layer_status(db_session, "p7")
        sess = result[0]["sessions"][0]
        assert sess["session_id"] == "init:p7:skill_fetch"
        assert sess["status"] == SessionStatus.DONE
        assert sess["started_at"] is not None
        assert sess["finished_at"] is not None
        assert sess["error"] is None

    async def test_ignores_non_init_sessions(self, db_session):
        """Should only return init-type sessions."""
        db_session.add_all([
            Session(session_id="init:p8:skill_fetch", type="init", ref_id="p8", layer=1, status=SessionStatus.DONE),
            Session(session_id="task:t1:plan", type="plan", ref_id="p8", status=SessionStatus.DONE),
        ])
        await db_session.commit()

        result = await get_init_layer_status(db_session, "p8")
        assert len(result) == 1
        assert len(result[0]["sessions"]) == 1


# ── Recovery Tests ──


def _recovery_patches(db_session):
    """Context manager helper for patching recovery dependencies.

    Since _recover_interrupted_sessions uses local imports, we patch
    at the source module level (daiflow.database, daiflow.ws_manager).
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_bg():
        yield db_session

    mock_ws = AsyncMock()

    return (
        patch("daiflow.database.get_background_db", return_value=fake_bg()),
        patch("daiflow.ws_manager.ws_manager", mock_ws),
        patch("daiflow.services.project_service.run_init_retry", new_callable=AsyncMock),
        patch("asyncio.create_task"),
        mock_ws,
    )


class TestRecoverInterruptedSessions:
    async def test_marks_running_sessions_failed(self, db_session):
        """Interrupted RUNNING sessions should be marked as FAILED."""
        from daiflow.main import _recover_interrupted_sessions

        db_session.add_all([
            Session(session_id="s_run_1", type="plan", ref_id="t1", status=SessionStatus.RUNNING),
            Session(session_id="s_run_2", type="todo_exec", ref_id="t2", status=SessionStatus.RUNNING),
            Session(session_id="s_done", type="plan", ref_id="t3", status=SessionStatus.DONE),
        ])
        await db_session.commit()

        p1, p2, p3, p4, mock_ws = _recovery_patches(db_session)
        with p1, p2, p3, p4:
            await _recover_interrupted_sessions()

        s1 = await db_session.get(Session, "s_run_1")
        s2 = await db_session.get(Session, "s_run_2")
        s_done = await db_session.get(Session, "s_done")

        assert s1.status == SessionStatus.FAILED
        assert s1.error == "Interrupted by server shutdown"
        assert s2.status == SessionStatus.FAILED
        assert s_done.status == SessionStatus.DONE  # Unchanged

    async def test_publishes_ws_events(self, db_session):
        """Recovery should publish WS status_change events."""
        from daiflow.main import _recover_interrupted_sessions

        db_session.add(Session(
            session_id="s_ws_test", type="plan", ref_id="t1", status=SessionStatus.RUNNING,
        ))
        await db_session.commit()

        p1, p2, p3, p4, mock_ws = _recovery_patches(db_session)
        with p1, p2, p3, p4:
            await _recover_interrupted_sessions()

        # Should have published a status_change event
        mock_ws.publish.assert_called()
        calls = mock_ws.publish.call_args_list
        ws_call = [c for c in calls if "session:s_ws_test" in str(c)]
        assert len(ws_call) >= 1

    async def test_resets_stuck_running_todos(self, db_session):
        """RUNNING todos should be reset to FAILED."""
        from daiflow.main import _recover_interrupted_sessions
        from daiflow.models import Project, Task

        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.flush()

        todo_running = Todo(task_id=t.id, seq=1, title="T1", status=TodoStatus.RUNNING)
        todo_done = Todo(task_id=t.id, seq=2, title="T2", status=TodoStatus.DONE)
        db_session.add_all([todo_running, todo_done])
        await db_session.commit()

        running_id = todo_running.id
        done_id = todo_done.id

        p1, p2, p3, p4, mock_ws = _recovery_patches(db_session)
        with p1, p2, p3, p4:
            await _recover_interrupted_sessions()

        todo_r = await db_session.get(Todo, running_id)
        todo_d = await db_session.get(Todo, done_id)

        assert todo_r.status == TodoStatus.FAILED
        assert todo_d.status == TodoStatus.DONE  # Unchanged

    async def test_auto_retries_init_sessions(self, db_session):
        """Interrupted init sessions should trigger auto-retry."""
        from daiflow.main import _recover_interrupted_sessions

        db_session.add_all([
            Session(session_id="init:p1:skill_fetch", type="init", ref_id="p1", layer=1, status=SessionStatus.RUNNING),
            Session(session_id="init:p1:repo_clone", type="init", ref_id="p1", layer=1, status=SessionStatus.RUNNING),
        ])
        await db_session.commit()

        p1, p2, p3, p4, mock_ws = _recovery_patches(db_session)
        with p1, p2, p3, p4 as mock_create_task:
            await _recover_interrupted_sessions()

        # create_task should have been called for auto-retry
        mock_create_task.assert_called_once()

    async def test_no_interrupted_sessions(self, db_session):
        """When no sessions are interrupted, nothing should happen."""
        from daiflow.main import _recover_interrupted_sessions

        db_session.add(Session(
            session_id="s_ok", type="plan", ref_id="t1", status=SessionStatus.DONE,
        ))
        await db_session.commit()

        p1, p2, p3, p4, mock_ws = _recovery_patches(db_session)
        with p1, p2, p3, p4:
            await _recover_interrupted_sessions()

        # No WS events should be published
        mock_ws.publish.assert_not_called()


# ── Constitution Layer Tests ──


class TestComputeInitSessionsConstitution:
    """Tests for compute_init_sessions including the Layer 5 constitution entry."""

    def test_includes_layer5_constitution_session(self):
        """compute_init_sessions should include a Layer 5 constitution entry."""
        repos = [SimpleNamespace(repo_type="frontend")]
        sessions = compute_init_sessions("proj_const_test", repos)

        layer5_sessions = [s for s in sessions if s.get("layer") == 5]
        assert len(layer5_sessions) >= 1, (
            "No Layer 5 sessions found. "
            "Add constitution session (layer=5) to compute_init_sessions()."
        )

    def test_layer5_session_id_contains_constitution(self):
        """The Layer 5 session should have a session_id referencing 'constitution'."""
        repos = [SimpleNamespace(repo_type="backend")]
        sessions = compute_init_sessions("proj_const_sid", repos)

        layer5 = [s for s in sessions if s.get("layer") == 5]
        assert any("constitution" in s["session_id"] for s in layer5), (
            "Layer 5 session_id must contain 'constitution'. "
            "Expected something like 'init:proj_const_sid:constitution'."
        )

    def test_layer5_type_is_init(self):
        """Layer 5 session must have type='init' for consistency."""
        repos = [SimpleNamespace(repo_type="custom")]
        sessions = compute_init_sessions("proj_const_type", repos)

        layer5 = [s for s in sessions if s.get("layer") == 5]
        for s in layer5:
            assert s["type"] == "init"
            assert s["ref_id"] == "proj_const_type"

    def test_existing_layers_unchanged(self):
        """Adding Layer 5 must not remove or change existing Layer 1-4 sessions."""
        repos = [SimpleNamespace(repo_type="frontend")]
        sessions = compute_init_sessions("proj_layers_test", repos)

        by_layer: dict[int, list] = {}
        for s in sessions:
            layer = s.get("layer", 0)
            by_layer.setdefault(layer, []).append(s)

        # Layer 1: repo_clone
        assert 1 in by_layer
        layer1_ids = [s["session_id"] for s in by_layer[1]]
        assert any("repo_clone" in sid for sid in layer1_ids)

        # Layer 4: project_md
        assert 4 in by_layer
        layer4_ids = [s["session_id"] for s in by_layer[4]]
        assert any("project_md" in sid for sid in layer4_ids)

    def test_constitution_session_is_after_layer4(self):
        """Layer 5 must come after Layer 4 in the session list (execution order)."""
        repos = [SimpleNamespace(repo_type="backend")]
        sessions = compute_init_sessions("proj_order", repos)

        layers_in_order = [s.get("layer") for s in sessions]
        last_layer4_idx = max(
            (i for i, l in enumerate(layers_in_order) if l == 4),
            default=-1,
        )
        first_layer5_idx = min(
            (i for i, l in enumerate(layers_in_order) if l == 5),
            default=len(sessions),
        )
        assert first_layer5_idx > last_layer4_idx, (
            "Layer 5 constitution must appear after Layer 4 project_md in session list."
        )


class TestRunInitConstitutionStep:
    """Tests that run_init executes the constitution step after Layer 4."""

    async def test_run_init_calls_constitution_after_layer4(self, db_session):
        """run_init must invoke the constitution generation step."""
        from contextlib import asynccontextmanager
        from daiflow.models import Project, ProjectRepo
        from daiflow.services.project_service import run_init

        proj = Project(id="proj_run_init_const", name="test")
        db_session.add(proj)
        await db_session.flush()
        repo = ProjectRepo(
            project_id=proj.id, repo_type="backend",
            git_url="https://example.com/repo.git",
        )
        db_session.add(repo)
        await db_session.commit()

        @asynccontextmanager
        async def fake_bg():
            yield db_session

        with patch("daiflow.services.project_service.get_background_db", return_value=fake_bg()), \
             patch("daiflow.services.project_service._run_layer", new_callable=AsyncMock, return_value=True), \
             patch("daiflow.services.project_service._run_layer4", new_callable=AsyncMock) as mock_layer4, \
             patch("daiflow.services.project_service._run_constitution", new_callable=AsyncMock) as mock_const, \
             patch("daiflow.services.project_service._finalize_init", new_callable=AsyncMock), \
             patch("daiflow.workflow.pipeline.run_simple_task", new_callable=AsyncMock), \
             patch("daiflow.services.project_service.get_language_setting",
                   new_callable=AsyncMock, return_value="zh"), \
             patch("daiflow.services.project_service._resolve_allowed_roots", return_value=["/tmp"]):
            await run_init("proj_run_init_const")

        mock_const.assert_called_once(), (
            "_run_constitution was not called. "
            "Add `await _run_constitution(...)` after _run_layer4 in run_init()."
        )

    async def test_run_init_constitution_after_layer4_ordering(self, db_session):
        """_run_constitution must be called AFTER _run_layer4 (not before)."""
        from contextlib import asynccontextmanager
        from daiflow.models import Project, ProjectRepo
        from daiflow.services.project_service import run_init

        call_order: list[str] = []

        async def mock_layer4(*args, **kwargs):
            call_order.append("layer4")

        async def mock_constitution(*args, **kwargs):
            call_order.append("constitution")

        proj = Project(id="proj_order_test", name="test")
        db_session.add(proj)
        await db_session.flush()
        repo = ProjectRepo(
            project_id=proj.id, repo_type="backend",
            git_url="https://example.com/repo.git",
        )
        db_session.add(repo)
        await db_session.commit()

        @asynccontextmanager
        async def fake_bg():
            yield db_session

        with patch("daiflow.services.project_service.get_background_db", return_value=fake_bg()), \
             patch("daiflow.services.project_service._run_layer", new_callable=AsyncMock, return_value=True), \
             patch("daiflow.services.project_service._run_layer4", side_effect=mock_layer4), \
             patch("daiflow.services.project_service._run_constitution", side_effect=mock_constitution), \
             patch("daiflow.services.project_service._finalize_init", new_callable=AsyncMock), \
             patch("daiflow.workflow.pipeline.run_simple_task", new_callable=AsyncMock), \
             patch("daiflow.services.project_service.get_language_setting",
                   new_callable=AsyncMock, return_value="zh"), \
             patch("daiflow.services.project_service._resolve_allowed_roots", return_value=["/tmp"]):
            await run_init("proj_order_test")

        assert "layer4" in call_order
        assert "constitution" in call_order
        assert call_order.index("constitution") > call_order.index("layer4"), (
            f"constitution must come AFTER layer4 in: {call_order}"
        )


class TestConstitutionPromptTemplate:
    """Tests for CONSTITUTION_PROMPT_TEMPLATE in prompts/__init__.py."""

    def test_constitution_prompt_exists(self):
        """CONSTITUTION_PROMPT_TEMPLATE must be defined in prompts module."""
        from daiflow.prompts import CONSTITUTION_PROMPT_TEMPLATE
        assert CONSTITUTION_PROMPT_TEMPLATE
        assert len(CONSTITUTION_PROMPT_TEMPLATE) > 50

    def test_constitution_prompt_mentions_output_path(self):
        """CONSTITUTION_PROMPT_TEMPLATE must have {output_path} placeholder."""
        from daiflow.prompts import CONSTITUTION_PROMPT_TEMPLATE
        assert "{output_path}" in CONSTITUTION_PROMPT_TEMPLATE

    def test_constitution_prompt_mentions_constitution(self):
        """Prompt should reference constitution.md as the output file."""
        from daiflow.prompts import CONSTITUTION_PROMPT_TEMPLATE
        assert "constitution" in CONSTITUTION_PROMPT_TEMPLATE.lower()
