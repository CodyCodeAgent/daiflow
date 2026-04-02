"""Plan agent: generates technical plan from task description."""

import base64
import json
import logging
from pathlib import Path

from sqlalchemy import select

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.config import TASKS_DIR
from daiflow.exceptions import InvalidStateError
from daiflow.prompts import PLAN_CHAT_PREFIX, PLAN_PROMPT_TEMPLATE
from daiflow.services.cody_service import append_path_boundary
from daiflow.session_runner import make_file_write_detector

logger = logging.getLogger(__name__)

# Media type mapping for image extensions
_EXT_TO_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _resolve_generated_plan_path(task_dir: Path) -> Path | None:
    """Locate generated plan file."""
    plan_path = task_dir / "plan.md"
    return plan_path if plan_path.exists() and plan_path.is_file() else None


class PlanAgent(AgentConfig):
    agent_type = "plan"
    chattable = True

    async def build_prompt(self, ctx: AgentContext):
        task = ctx.task
        task_dir = Path(ctx.task_dir)
        plan_path = task_dir / "plan.md"
        spec_path = task_dir / "spec.md"

        spec_context = ""
        if spec_path.exists():
            spec_context = f"## Functional Specification\nSee `{spec_path}`.\n\n"
        elif task.spec_doc:
            spec_context = (
                "## Functional Specification\n"
                f"```markdown\n{task.spec_doc}\n```\n\n"
            )

        doc_links = ""
        if task.prd_doc_url:
            doc_links += (
                f"## PRD Document Link\n"
                f"Linked document: {task.prd_doc_url}\n"
                f"Use an MCP tool to read this document and incorporate its content.\n\n"
            )
        if task.tech_doc_url:
            doc_links += (
                f"## Technical Document Link\n"
                f"Linked document: {task.tech_doc_url}\n"
                f"Use an MCP tool to read this document.\n\n"
            )

        text = PLAN_PROMPT_TEMPLATE.format(
            description=task.description or "(none)",
            prd=task.prd or "(none)",
            spec_context=spec_context,
            tech_plan=task.tech_plan or "(none)",
            doc_links=doc_links,
            plan_path=plan_path,
        )

        # Check for PRD images
        image_filenames = json.loads(task.prd_images or "[]")
        text_with_boundary = append_path_boundary(text, ctx.task_dir, ctx.allowed_roots)
        if not image_filenames:
            return text_with_boundary

        # Build MultimodalPrompt with images
        try:
            from cody.core.prompt import MultimodalPrompt, ImageData
        except ImportError:
            logger.warning("cody.core.prompt not available, falling back to text-only prompt")
            return text_with_boundary

        images = []
        img_dir = TASKS_DIR / task.id / "prd_images"
        for filename in image_filenames:
            img_path = img_dir / filename
            if not img_path.exists():
                continue
            data = base64.b64encode(img_path.read_bytes()).decode()
            ext = img_path.suffix.lower()
            media_type = _EXT_TO_MEDIA.get(ext, "image/png")
            images.append(ImageData(data=data, media_type=media_type, filename=filename))

        if not images:
            return text_with_boundary

        return MultimodalPrompt(text=text_with_boundary, images=images)

    def build_artifact_detector(self, ctx: AgentContext):
        async def on_plan_match(_file_path):
            plan_path = _resolve_generated_plan_path(Path(ctx.task_dir))
            if not plan_path:
                return None
            content = plan_path.read_text(encoding="utf-8")
            # Re-fetch to avoid StaleDataError if task was deleted mid-execution
            from daiflow.models import Task
            task = await ctx.db.get(Task, ctx.task.id)
            if task:
                canonical_plan = Path(ctx.task_dir) / "plan.md"
                if plan_path != canonical_plan:
                    canonical_plan.write_text(content, encoding="utf-8")
                task.tech_plan = content
                await ctx.db.commit()
            return content

        return make_file_write_detector("plan.md", "plan_updated", on_plan_match)

    async def on_complete(self, ctx: AgentContext) -> None:
        from daiflow.models import Task
        # Re-fetch task in case it was deleted during execution
        task = await ctx.db.get(Task, ctx.task.id)
        if not task:
            return
        plan_path = _resolve_generated_plan_path(Path(ctx.task_dir))
        if not plan_path:
            raise InvalidStateError(
                "Plan generation finished but no plan file was produced. "
                "Please retry with richer requirement input."
            )

        content = plan_path.read_text(encoding="utf-8")
        if not content.strip():
            raise InvalidStateError(
                "Plan generation produced an empty document. Please retry with clearer context."
            )

        canonical_plan = Path(ctx.task_dir) / "plan.md"
        if plan_path != canonical_plan:
            canonical_plan.write_text(content, encoding="utf-8")
        task.tech_plan = content
        await ctx.db.commit()

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        plan_path = Path(ctx.task_dir) / "plan.md"
        return PLAN_CHAT_PREFIX.format(plan_path=plan_path)


register_agent(PlanAgent())
