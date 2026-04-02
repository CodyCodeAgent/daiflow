"""Tests for SpecAgent: registration, prompt building, artifact detection, on_complete.

Implementation contract:
  - agent_type = "spec"
  - chattable = True
  - build_prompt: uses built-in SPEC_PROMPT_TEMPLATE
  - build_artifact_detector: detects spec.md writes, publishes spec_updated event
  - on_complete: reads spec.md from disk and persists to task.spec_doc
  - chat_system_prefix: returns context for spec refinement chat
"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from daiflow.agents import (
    AgentContext,
    AgentConfig,
    _AGENT_REGISTRY,
    get_agent_config,
    register_agent,
)


# ── Helper ──


def _make_ctx(task_dir: str, task, db=None):
    return AgentContext(
        db=db or AsyncMock(),
        session_id="s_spec_1",
        entity_id=task.id if hasattr(task, "id") else "t_spec_1",
        task=task,
        task_dir=task_dir,
        allowed_roots=[task_dir],
    )


def _make_task(task_id="t1", description="Build login feature", prd="Login PRD", spec_doc=""):
    return SimpleNamespace(
        id=task_id,
        name="Test Task",
        project_id="p1",
        description=description,
        prd=prd,
        spec_doc=spec_doc,
        tech_plan="",
        prd_doc_url="",
        prd_images="[]",
        tech_doc_url="",
    )


# ── Registry tests ──


class TestSpecAgentRegistry:
    def test_spec_agent_registered(self):
        """SpecAgent must be in the global registry after import."""
        assert "spec" in _AGENT_REGISTRY, (
            "SpecAgent not registered. Did you add `from daiflow.agents import spec_agent` "
            "to _auto_register() in agents/__init__.py?"
        )

    def test_spec_agent_chattable(self):
        """SpecAgent must be chattable (supports /adk:specify refinement chat)."""
        config = get_agent_config("spec")
        assert config.chattable is True

    def test_spec_agent_is_agent_config(self):
        """SpecAgent instance must inherit from AgentConfig."""
        config = get_agent_config("spec")
        assert isinstance(config, AgentConfig)

    def test_all_agents_registered_including_spec(self):
        """All expected agent types must be registered after the addition."""
        expected = {"plan", "todo_split", "todo_exec", "review", "init", "spec"}
        registered = set(_AGENT_REGISTRY.keys())
        missing = expected - registered
        assert not missing, f"Missing agent types: {missing}"

    def test_spec_agent_has_correct_type(self):
        config = get_agent_config("spec")
        assert config.agent_type == "spec"


# ── build_prompt tests ──


class TestSpecAgentBuildPrompt:
    async def test_build_prompt_uses_builtin_template(self):
        """Prompt uses built-in SPEC_PROMPT_TEMPLATE."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = _make_task()
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            prompt = await config.build_prompt(ctx)
            prompt_text = str(prompt)

            # Must include the spec output path
            assert "spec.md" in prompt_text
            # Must include task context
            assert task.description in prompt_text or task.prd in prompt_text

    async def test_build_prompt_includes_spec_path(self):
        """Prompt must contain the exact spec.md output path in task_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = _make_task()
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            prompt = await config.build_prompt(ctx)
            prompt_text = str(prompt)

            expected_path = str(Path(tmpdir) / "spec.md")
            assert expected_path in prompt_text

    async def test_build_prompt_includes_prd_when_present(self):
        """PRD content should appear in the prompt for spec generation context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = _make_task(prd="User Story: As a user I want to login")
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            prompt = await config.build_prompt(ctx)
            prompt_text = str(prompt)

            assert "User Story" in prompt_text or "login" in prompt_text

    async def test_build_prompt_missing_prd_still_builds(self):
        """Build prompt must succeed even when task.prd is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = _make_task(prd="", description="Add dark mode")
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            prompt = await config.build_prompt(ctx)
            assert prompt  # non-empty


# ── Artifact detector tests ──


class TestSpecAgentArtifactDetector:
    def test_build_artifact_detector_returns_callable(self):
        """build_artifact_detector must return a callable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = _make_task()
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            detector = config.build_artifact_detector(ctx)
            assert callable(detector)

    async def test_detector_fires_on_spec_md_write(self):
        """Detector should return a spec_updated event when spec.md is written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.md"
            spec_path.write_text("# Spec Content\n\nFR-001: User can login")

            task = _make_task()
            db = AsyncMock()
            ctx = _make_ctx(tmpdir, task, db=db)
            config = get_agent_config("spec")
            detector = config.build_artifact_detector(ctx)

            event = {
                "type": "tool_result",
                "tool_name": "write_file",
                "args": {"path": str(spec_path)},
            }
            result = await detector(event)

            assert result is not None
            assert result["type"] == "spec_updated"

    async def test_detector_result_contains_spec_content(self):
        """spec_updated event content should include the written spec.md content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.md"
            spec_path.write_text("# My Spec\n\nAcceptance Criteria: ...")

            task = _make_task()
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            detector = config.build_artifact_detector(ctx)

            result = await detector({
                "tool_name": "write_file",
                "args": {"path": str(spec_path)},
            })

            assert result is not None
            assert "My Spec" in (result.get("content") or "")

    async def test_detector_syncs_spec_doc_to_task_object(self):
        """Detector should update task.spec_doc and commit to DB after spec.md write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.md"
            spec_content = "# Integration Spec\n\nFR-001: ..."
            spec_path.write_text(spec_content)

            task = _make_task()
            task.spec_doc = "old content"
            db = AsyncMock()
            # db.get returns the same task object so spec_doc update is visible
            db.get = AsyncMock(return_value=task)
            ctx = _make_ctx(tmpdir, task, db=db)
            config = get_agent_config("spec")
            detector = config.build_artifact_detector(ctx)

            await detector({
                "tool_name": "write_file",
                "args": {"path": str(spec_path)},
            })

            assert task.spec_doc == spec_content
            db.commit.assert_awaited()

    async def test_detector_ignores_non_spec_file_writes(self):
        """Writing a non-spec.md file should not trigger spec_updated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            other_path = Path(tmpdir) / "plan.md"
            other_path.write_text("# Plan content")

            task = _make_task()
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            detector = config.build_artifact_detector(ctx)

            result = await detector({
                "tool_name": "write_file",
                "args": {"path": str(other_path)},
            })

            assert result is None

    async def test_detector_ignores_non_write_tool_events(self):
        """Non-file-write tool events should be ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = _make_task()
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            detector = config.build_artifact_detector(ctx)

            for event in [
                {"type": "text_delta", "content": "hello"},
                {"tool_name": "read_file", "args": {"path": "/some/file.md"}},
                {"tool_name": "exec_command", "args": {"command": "ls"}},
            ]:
                result = await detector(event)
                assert result is None, f"Expected None for event {event}, got {result}"


# ── on_complete tests ──


class TestSpecAgentOnComplete:
    async def test_on_complete_reads_spec_from_disk(self, db_session):
        """on_complete should read spec.md from task_dir and persist to task.spec_doc in DB."""
        from daiflow.models import Project, Task

        project = Project(id="p_spec_oc", name="test")
        db_session.add(project)
        await db_session.flush()

        task = Task(id="t_spec_oc", name="test task", project_id=project.id)
        db_session.add(task)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.md"
            spec_content = "# Final Spec\n\nFR-001: Login\nFR-002: Register"
            spec_path.write_text(spec_content)

            ctx = AgentContext(
                db=db_session,
                session_id="s1",
                entity_id=task.id,
                task=task,
                task_dir=tmpdir,
                allowed_roots=[tmpdir],
            )
            config = get_agent_config("spec")
            await config.on_complete(ctx)

        refreshed = await db_session.get(Task, task.id)
        assert refreshed.spec_doc == spec_content

    async def test_on_complete_handles_missing_spec_file(self, db_session):
        """on_complete should not crash if spec.md doesn't exist; spec_doc unchanged."""
        from daiflow.models import Project, Task

        project = Project(id="p_spec_missing", name="test")
        db_session.add(project)
        await db_session.flush()

        task = Task(id="t_spec_missing", name="test task", project_id=project.id,
                    spec_doc="pre-existing content")
        db_session.add(task)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            # spec.md does NOT exist
            ctx = AgentContext(
                db=db_session,
                session_id="s1",
                entity_id=task.id,
                task=task,
                task_dir=tmpdir,
                allowed_roots=[tmpdir],
            )
            config = get_agent_config("spec")
            await config.on_complete(ctx)  # Must not raise

        refreshed = await db_session.get(Task, task.id)
        # Unchanged when file missing
        assert refreshed.spec_doc == "pre-existing content"

    async def test_on_complete_noop_when_task_deleted(self, db_session):
        """on_complete should be a no-op when the task was deleted mid-execution."""
        from daiflow.models import Project, Task

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "spec.md").write_text("# Spec")

            ctx = AgentContext(
                db=db_session,
                session_id="s1",
                entity_id="deleted_task_id",
                task=SimpleNamespace(id="deleted_task_id", spec_doc=""),
                task_dir=tmpdir,
                allowed_roots=[tmpdir],
            )
            # db.get returns None → task was deleted
            config = get_agent_config("spec")
            await config.on_complete(ctx)  # Must not raise


# ── chat_system_prefix tests ──


class TestSpecAgentChatSystemPrefix:
    def test_chat_system_prefix_returns_string(self):
        """chat_system_prefix must return a non-empty string for spec refinement chat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = _make_task()
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            prefix = config.chat_system_prefix(ctx)
            assert isinstance(prefix, str)
            assert len(prefix) > 0

    def test_chat_system_prefix_references_spec_path(self):
        """The system prefix should guide the AI to update spec.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = _make_task()
            ctx = _make_ctx(tmpdir, task)
            config = get_agent_config("spec")
            prefix = config.chat_system_prefix(ctx)
            assert "spec" in prefix.lower()
