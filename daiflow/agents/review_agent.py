"""Review agent: chat-only agent for the review stage.

The review stage does NOT use SessionRunner.run() for AI execution —
generate_commit_message() calls Cody client directly. But review chat
still goes through run_stage_chat(), so we register an AgentConfig to
support prepare_chat().
"""

from sqlalchemy import select

from pathlib import Path

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.models import Session
from daiflow.prompts import REVIEW_CHAT_PREFIX
from daiflow.session_runner import make_file_write_detector


class ReviewAgent(AgentConfig):
    agent_type = "review"
    chattable = True

    async def build_prompt(self, ctx: AgentContext) -> str:
        # Review does not use SessionRunner.run(), so this is not called
        raise NotImplementedError("Review agent does not support SessionRunner.run()")

    async def resolve_cody_session_id(self, ctx: AgentContext) -> str | None:
        result = await ctx.db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == ctx.entity_id,
                Session.type == "review",
            )
        )
        return result.scalar()

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        task = ctx.task
        plan_path = Path(ctx.task_dir) / "plan.md"
        return REVIEW_CHAT_PREFIX.format(
            task_name=task.name if task else "",
            task_description=task.description if task else "",
            plan_path=plan_path,
            task_dir=ctx.task_dir,
        )

    def build_artifact_detector(self, ctx: AgentContext):
        return make_file_write_detector(None, "code_updated")


register_agent(ReviewAgent())
