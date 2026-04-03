"""Tests for service-layer coverage: git, skill, runner, config, and todo_machine."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import DAIFLOW_HOME, PROJECTS_DIR, TASKS_DIR, safe_filename, utc_iso
from daiflow.models import Project, RunnerConfig, Setting, Task, Todo, TodoStatus
from daiflow.services.git_service import validate_branch_name
from daiflow.services.runner_service import mask_runner_config, resolve_runner_config
from daiflow.services.skill_service import (
    get_project_dir,
    get_project_skills_dir,
    get_task_dir,
    get_task_skills_dir,
)
from daiflow.workflow.todo_machine import TodoWorkflow


# ---------------------------------------------------------------------------
# 1. git_service — validate_branch_name
# ---------------------------------------------------------------------------

class TestValidateBranchName:
    def test_valid_main(self):
        validate_branch_name("main")

    def test_valid_feature_slash(self):
        validate_branch_name("feature/foo")

    def test_valid_fix_with_hyphen(self):
        validate_branch_name("fix/bar-baz")

    def test_valid_version_tag(self):
        validate_branch_name("v1.0")

    def test_invalid_empty(self):
        with pytest.raises(ValueError):
            validate_branch_name("")

    def test_invalid_flag(self):
        with pytest.raises(ValueError):
            validate_branch_name("--flag")

    def test_invalid_double_dot(self):
        with pytest.raises(ValueError):
            validate_branch_name("foo..bar")

    def test_invalid_dot_lock(self):
        with pytest.raises(ValueError):
            validate_branch_name("foo.lock")

    def test_invalid_trailing_slash(self):
        with pytest.raises(ValueError):
            validate_branch_name("foo/")


# ---------------------------------------------------------------------------
# 2. skill_service — path helpers
# ---------------------------------------------------------------------------

class TestSkillServicePaths:
    def test_get_project_skills_dir(self):
        result = get_project_skills_dir("proj_123")
        assert result == PROJECTS_DIR / "proj_123" / "skills"

    def test_get_task_skills_dir(self):
        result = get_task_skills_dir("task_456")
        assert result == TASKS_DIR / "task_456" / ".cody" / "skills"

    def test_get_task_dir_creates_dir(self):
        tid = f"test_task_{uuid.uuid4().hex[:8]}"
        result = get_task_dir(tid)
        assert result == TASKS_DIR / tid
        assert result.is_dir()

    def test_get_project_dir_creates_dir(self):
        pid = f"test_proj_{uuid.uuid4().hex[:8]}"
        result = get_project_dir(pid)
        assert result == PROJECTS_DIR / pid
        assert result.is_dir()

    def test_paths_under_daiflow_home(self):
        """All paths should live under the test DAIFLOW_HOME."""
        assert str(get_project_skills_dir("x")).startswith(str(DAIFLOW_HOME))
        assert str(get_task_skills_dir("x")).startswith(str(DAIFLOW_HOME))


# ---------------------------------------------------------------------------
# 3. runner_service — resolve_runner_config + mask_runner_config
# ---------------------------------------------------------------------------

class TestResolveRunnerConfig:
    async def test_task_level_override(self, db_session: AsyncSession):
        rc = RunnerConfig(id="rc_task", type="cody", name="Task Runner")
        proj = Project(id="proj_r1", name="P")
        task = Task(id="task_r1", name="T", project_id="proj_r1", runner_id="rc_task")
        db_session.add_all([rc, proj, task])
        await db_session.commit()

        result = await resolve_runner_config(db_session, project_id="proj_r1", task_id="task_r1")
        assert result is not None
        assert result.id == "rc_task"

    async def test_project_level_fallback(self, db_session: AsyncSession):
        rc = RunnerConfig(id="rc_proj", type="claude_code", name="Project Runner")
        proj = Project(id="proj_r2", name="P", runner_id="rc_proj")
        task = Task(id="task_r2", name="T", project_id="proj_r2")  # no runner_id
        db_session.add_all([rc, proj, task])
        await db_session.commit()

        result = await resolve_runner_config(db_session, project_id="proj_r2", task_id="task_r2")
        assert result is not None
        assert result.id == "rc_proj"

    async def test_global_default_fallback(self, db_session: AsyncSession):
        rc = RunnerConfig(id="rc_global", type="cody", name="Global Runner")
        proj = Project(id="proj_r3", name="P")  # no runner_id
        db_session.add_all([rc, proj, Setting(key="default_runner_id", value="rc_global")])
        await db_session.commit()

        result = await resolve_runner_config(db_session, project_id="proj_r3")
        assert result is not None
        assert result.id == "rc_global"

    async def test_none_when_nothing_configured(self, db_session: AsyncSession):
        proj = Project(id="proj_r4", name="P")
        task = Task(id="task_r4", name="T", project_id="proj_r4")
        db_session.add_all([proj, task])
        await db_session.commit()

        result = await resolve_runner_config(db_session, project_id="proj_r4", task_id="task_r4")
        assert result is None

    async def test_none_with_no_args(self, db_session: AsyncSession):
        result = await resolve_runner_config(db_session)
        assert result is None


class TestMaskRunnerConfig:
    def test_masks_long_api_key(self):
        config = {"api_key": "sk-1234567890abcdef", "model": "gpt-4"}
        masked = mask_runner_config(config)
        assert masked["model"] == "gpt-4"
        assert masked["api_key"].startswith("sk-1")
        assert masked["api_key"].endswith("cdef")
        assert "*" in masked["api_key"]
        # Original unchanged
        assert config["api_key"] == "sk-1234567890abcdef"

    def test_masks_short_api_key(self):
        masked = mask_runner_config({"api_key": "short"})
        assert masked["api_key"] == "****"

    def test_no_api_key(self):
        config = {"model": "gpt-4"}
        masked = mask_runner_config(config)
        assert masked == {"model": "gpt-4"}

    def test_empty_api_key(self):
        masked = mask_runner_config({"api_key": ""})
        assert masked["api_key"] == ""


# ---------------------------------------------------------------------------
# 4. config — safe_filename, utc_iso
# ---------------------------------------------------------------------------

class TestSafeFilename:
    def test_replaces_colons(self):
        assert safe_filename("session:task:42:plan") == "session_task_42_plan"

    def test_replaces_multiple_unsafe_chars(self):
        assert safe_filename('a:b*c?d"e<f>g|h') == "a_b_c_d_e_f_g_h"

    def test_preserves_safe_chars(self):
        assert safe_filename("hello-world_123.jsonl") == "hello-world_123.jsonl"

    def test_replaces_backslash(self):
        assert safe_filename("a\\b") == "a_b"

    def test_empty_string(self):
        assert safe_filename("") == ""


class TestUtcIso:
    def test_utc_datetime(self):
        dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = utc_iso(dt)
        assert result == "2025-01-15T10:30:00Z"

    def test_naive_datetime_gets_z_suffix(self):
        dt = datetime(2025, 6, 1, 12, 0, 0)
        result = utc_iso(dt)
        assert result.endswith("Z")

    def test_aware_utc_replaces_offset(self):
        dt = datetime(2025, 3, 20, 8, 0, 0, tzinfo=timezone.utc)
        result = utc_iso(dt)
        assert "+00:00" not in result
        assert result.endswith("Z")


# ---------------------------------------------------------------------------
# 5. todo_machine — predecessor deleted guard
# ---------------------------------------------------------------------------

class TestTodoMachinePredecessorGuard:
    async def test_deleted_predecessor_allows_execution(self, db_session: AsyncSession):
        """When predecessor todo is deleted (not in DB), guard should pass."""
        proj = Project(id="proj_tm", name="P")
        task = Task(id="task_tm", name="T", project_id="proj_tm")
        # Create todo with seq=2, but no seq=1 predecessor exists
        todo = Todo(id="todo_tm_2", task_id="task_tm", seq=2, title="Second", status=TodoStatus.PENDING)
        db_session.add_all([proj, task, todo])
        await db_session.commit()

        wf = TodoWorkflow(todo, db_session)
        # execute triggers _prev_todo_completed guard; should pass since predecessor is missing
        await wf.execute()
        assert todo.status == TodoStatus.RUNNING

    async def test_first_todo_always_passes(self, db_session: AsyncSession):
        """First todo (seq=1) should always be allowed to execute."""
        proj = Project(id="proj_tm2", name="P")
        task = Task(id="task_tm2", name="T", project_id="proj_tm2")
        todo = Todo(id="todo_tm_1", task_id="task_tm2", seq=1, title="First", status=TodoStatus.PENDING)
        db_session.add_all([proj, task, todo])
        await db_session.commit()

        wf = TodoWorkflow(todo, db_session)
        await wf.execute()
        assert todo.status == TodoStatus.RUNNING

    async def test_predecessor_done_allows_execution(self, db_session: AsyncSession):
        """When predecessor is DONE, second todo can execute."""
        proj = Project(id="proj_tm3", name="P")
        task = Task(id="task_tm3", name="T", project_id="proj_tm3")
        todo1 = Todo(id="todo_tm3_1", task_id="task_tm3", seq=1, title="First", status=TodoStatus.DONE)
        todo2 = Todo(id="todo_tm3_2", task_id="task_tm3", seq=2, title="Second", status=TodoStatus.PENDING)
        db_session.add_all([proj, task, todo1, todo2])
        await db_session.commit()

        wf = TodoWorkflow(todo2, db_session)
        await wf.execute()
        assert todo2.status == TodoStatus.RUNNING

    async def test_predecessor_pending_blocks_execution(self, db_session: AsyncSession):
        """When predecessor is still PENDING, execution should be blocked."""
        proj = Project(id="proj_tm4", name="P")
        task = Task(id="task_tm4", name="T", project_id="proj_tm4")
        todo1 = Todo(id="todo_tm4_1", task_id="task_tm4", seq=1, title="First", status=TodoStatus.PENDING)
        todo2 = Todo(id="todo_tm4_2", task_id="task_tm4", seq=2, title="Second", status=TodoStatus.PENDING)
        db_session.add_all([proj, task, todo1, todo2])
        await db_session.commit()

        wf = TodoWorkflow(todo2, db_session)
        result = await wf.execute()
        assert not result
        assert todo2.status == TodoStatus.PENDING
