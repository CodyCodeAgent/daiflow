"""Spec agent: generates functional specification (spec.md) from PRD/description."""

import logging
from pathlib import Path

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.exceptions import InvalidStateError
from daiflow.prompts import SPEC_CHAT_PREFIX, SPEC_PROMPT_TEMPLATE
from daiflow.services.cody_service import append_path_boundary
from daiflow.session_runner import make_file_write_detector

logger = logging.getLogger(__name__)


def _resolve_generated_spec_path(task_dir: Path) -> Path | None:
    """Locate generated spec file."""
    spec_path = task_dir / "spec.md"
    return spec_path if spec_path.exists() and spec_path.is_file() else None


class SpecAgent(AgentConfig):
    """Agent that generates a functional specification (spec.md) from PRD/description."""

    agent_type = "spec"
    chattable = True

    async def build_prompt(self, ctx: AgentContext) -> str:
        task = ctx.task
        task_dir = Path(ctx.task_dir)
        spec_path = task_dir / "spec.md"

        if not task.prd and not task.description and not task.name:
            raise InvalidStateError(
                "Cannot generate spec: missing PRD/description/task name context."
            )

        doc_links = ""
        if task.prd_doc_url:
            doc_links += (
                f"\n## PRD Document Link\n"
                f"Linked document: {task.prd_doc_url}\n"
                f"Use an MCP tool to read this document and incorporate its content.\n"
            )
        if task.tech_doc_url:
            doc_links += (
                f"\n## Technical Document Link\n"
                f"Linked document: {task.tech_doc_url}\n"
                f"Use an MCP tool if this document is relevant to spec generation.\n"
            )

        text = SPEC_PROMPT_TEMPLATE.format(
            description=task.description or "(none)",
            prd=task.prd or "(none)",
            spec_path=spec_path,
        ) + doc_links
        return append_path_boundary(text, ctx.task_dir, ctx.allowed_roots)

    def build_artifact_detector(self, ctx: AgentContext):
        async def on_spec_match(_file_path: str | None) -> str | None:
            task_dir = Path(ctx.task_dir)
            spec_path = _resolve_generated_spec_path(task_dir)
            if not spec_path:
                return None
            content = spec_path.read_text(encoding="utf-8")
            # Re-fetch to avoid StaleDataError if task was deleted mid-execution
            from daiflow.models import Task
            task = await ctx.db.get(Task, ctx.entity_id)
            if task:
                task.spec_doc = content
                await ctx.db.commit()
            return content

        return make_file_write_detector("spec.md", "spec_updated", on_spec_match)

    async def on_complete(self, ctx: AgentContext) -> None:
        from daiflow.models import Task

        task = await ctx.db.get(Task, ctx.entity_id)
        if not task:
            return
        spec_path = _resolve_generated_spec_path(Path(ctx.task_dir))
        if not spec_path:
            return  # Agent didn't write spec.md; leave spec_doc unchanged

        content = spec_path.read_text(encoding="utf-8")
        if not content.strip():
            return  # Empty file; leave spec_doc unchanged

        # Normalize to task-root spec.md for frontend and downstream stages.
        canonical_spec = Path(ctx.task_dir) / "spec.md"
        if spec_path != canonical_spec:
            canonical_spec.write_text(content, encoding="utf-8")
        task.spec_doc = content
        await ctx.db.commit()

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        spec_path = Path(ctx.task_dir) / "spec.md"
        return SPEC_CHAT_PREFIX.format(spec_path=str(spec_path))


register_agent(SpecAgent())
