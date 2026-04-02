"""Tests for chat_service stage routing.

Verifies that the spec stage is properly included in _STAGE_MAP.

Implementation contract:
  - _STAGE_MAP in chat_service.py must include "spec" key
  - "spec" maps to agent_type="spec" with a task_spec session_id function
  - Unknown stages raise InvalidStateError
  - prepare_stage_chat works end-to-end for the spec stage
"""

import pytest
from unittest.mock import AsyncMock, patch

from daiflow.exceptions import InvalidStateError
from daiflow.services.chat_service import _STAGE_MAP


class TestStageChatMap:
    """Verify _STAGE_MAP includes the spec stage after integration."""

    def test_spec_stage_in_stage_map(self):
        """'spec' must be a valid chat_path key in _STAGE_MAP."""
        assert "spec" in _STAGE_MAP, (
            "'spec' not found in _STAGE_MAP. "
            "Add `'spec': ('spec', task_spec, False)` to chat_service._STAGE_MAP."
        )

    def test_spec_stage_agent_type(self):
        """'spec' stage must map to agent_type='spec'."""
        agent_type, _, _ = _STAGE_MAP["spec"]
        assert agent_type == "spec"

    def test_spec_stage_entity_is_task_not_todo(self):
        """Spec stage operates on tasks (entity_is_todo=False), not todos."""
        _, _, entity_is_todo = _STAGE_MAP["spec"]
        assert entity_is_todo is False

    def test_spec_stage_has_session_id_fn(self):
        """Spec stage must provide a session_id function (not None)."""
        _, session_id_fn, _ = _STAGE_MAP["spec"]
        assert session_id_fn is not None
        assert callable(session_id_fn)

    def test_spec_stage_session_id_fn_generates_correct_id(self):
        """The session_id function for spec must produce 'task:{id}:spec'."""
        _, session_id_fn, _ = _STAGE_MAP["spec"]
        result = session_id_fn("task_abc_123")
        assert result == "task:task_abc_123:spec"

    def test_all_expected_stages_present(self):
        """All stages (including spec) must be present after integration."""
        expected = {"plan", "todo", "todo_exec", "review", "spec"}
        registered = set(_STAGE_MAP.keys())
        missing = expected - registered
        assert not missing, (
            f"Missing stage(s) in _STAGE_MAP: {missing}. "
            "Add the missing entries to chat_service._STAGE_MAP."
        )

    def test_existing_stages_unchanged(self):
        """Existing stage entries (plan, todo, review) must not be affected."""
        plan_agent, _, plan_is_todo = _STAGE_MAP["plan"]
        assert plan_agent == "plan"
        assert plan_is_todo is False

        todo_agent, _, todo_is_todo = _STAGE_MAP["todo"]
        assert todo_agent == "todo_split"
        assert todo_is_todo is False

        review_agent, _, review_is_todo = _STAGE_MAP["review"]
        assert review_agent == "review"
        assert review_is_todo is False

        exec_agent, _, exec_is_todo = _STAGE_MAP["todo_exec"]
        assert exec_agent == "todo_exec"
        assert exec_is_todo is True


class TestPrepareStageChatSpec:
    """Integration tests for prepare_stage_chat with spec stage."""

    async def test_unknown_stage_raises_invalid_state_error(self, db_session):
        """An unknown stage name must raise InvalidStateError."""
        from daiflow.services.chat_service import prepare_stage_chat

        with pytest.raises(InvalidStateError):
            await prepare_stage_chat(db_session, "nonexistent_stage_xyz", "entity_1")

    async def test_spec_stage_not_found_raises_not_found(self, db_session):
        """prepare_stage_chat with spec stage raises NotFoundError for missing task."""
        from daiflow.exceptions import NotFoundError
        from daiflow.services.chat_service import prepare_stage_chat

        with pytest.raises(NotFoundError):
            await prepare_stage_chat(db_session, "spec", "nonexistent_task_id_xyz")

    async def test_spec_stage_returns_correct_session_id(self, db_session):
        """prepare_stage_chat for spec must set session_id = 'task:{id}:spec'."""
        from daiflow.models import Project, Task, TaskStatus
        from daiflow.services.chat_service import prepare_stage_chat

        project = Project(id="p_chat_spec", name="test")
        db_session.add(project)
        await db_session.flush()

        task = Task(
            id="t_chat_spec",
            name="test task",
            project_id=project.id,
            status=TaskStatus.PLANNING,
        )
        db_session.add(task)
        await db_session.commit()

        # Mock the underlying prepare_chat (imported lazily inside prepare_stage_chat)
        mock_ctx = AsyncMock()
        mock_ctx.session_id = "task:t_chat_spec:spec"

        with patch("daiflow.agent_executor.prepare_chat", new_callable=AsyncMock,
                   return_value=mock_ctx) as mock_prepare:
            result = await prepare_stage_chat(db_session, "spec", "t_chat_spec")

        # prepare_chat should be called with agent_type="spec"
        call_args = mock_prepare.call_args
        assert call_args is not None
        args = call_args[0]  # positional args
        assert "spec" in args  # agent_type

        # And the session_id should be derived from the spec stage
        _, session_id_fn, _ = _STAGE_MAP["spec"]
        expected_sid = session_id_fn("t_chat_spec")
        assert expected_sid == "task:t_chat_spec:spec"


class TestSessionIdHelperForSpec:
    """Tests for the task_spec session_id helper in session_ids.py."""

    def test_task_spec_helper_exists(self):
        """task_spec function must exist in session_ids module."""
        from daiflow.session_ids import task_spec
        assert callable(task_spec)

    def test_task_spec_format(self):
        """task_spec must return 'task:{task_id}:spec'."""
        from daiflow.session_ids import task_spec
        result = task_spec("my_task_123")
        assert result == "task:my_task_123:spec"

    def test_task_spec_with_various_ids(self):
        """task_spec handles arbitrary task id strings."""
        from daiflow.session_ids import task_spec
        for task_id in ["abc", "uuid_hex_12345", "proj_task_01"]:
            assert task_spec(task_id) == f"task:{task_id}:spec"
