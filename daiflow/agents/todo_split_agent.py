"""Todo-split agent: decomposes technical plan into actionable todos."""

import logging
from pathlib import Path

from sqlalchemy import select

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.models import Session
from daiflow.prompts import TODO_CHAT_PREFIX, TODO_PROMPT_TEMPLATE
from daiflow.services.cody_service import append_path_boundary
from daiflow.session_runner import make_file_write_detector

logger = logging.getLogger(__name__)


class TodoSplitAgent(AgentConfig):
    agent_type = "todo_split"
    chattable = True

    async def build_prompt(self, ctx: AgentContext) -> str:
        task_dir = Path(ctx.task_dir)
        todo_path = task_dir / "todo.json"
        text = TODO_PROMPT_TEMPLATE.format(todo_path=todo_path)
        return append_path_boundary(text, ctx.task_dir, ctx.allowed_roots)

    async def resolve_cody_session_id(self, ctx: AgentContext) -> str | None:
        # Reuse plan's cody_session_id for context continuity
        result = await ctx.db.execute(
            select(Session.cody_session_id).where(
                Session.task_id == ctx.entity_id,
                Session.type == "plan",
            )
        )
        return result.scalar()

    def build_artifact_detector(self, ctx: AgentContext):
        task_dir = Path(ctx.task_dir)
        todo_path = task_dir / "todo.json"

        async def on_todo_match(_file_path):
            if todo_path.exists():
                content = todo_path.read_text(encoding="utf-8")
                from daiflow.services.task_service import sync_todos_from_file
                try:
                    await sync_todos_from_file(ctx.db, ctx.entity_id, content)
                except Exception as e:
                    logger.warning(
                        "todo.json sync failed for task %s (mid-generation): %s",
                        ctx.entity_id, e,
                    )
                return content
            return None

        return make_file_write_detector("todo.json", "todo_updated", on_todo_match)

    async def on_complete(self, ctx: AgentContext) -> None:
        from daiflow.workflow import TaskWorkflow

        task = ctx.task
        task = await ctx.db.get(type(task), task.id)
        if not task:
            return

        task_dir = Path(ctx.task_dir)
        todo_path = task_dir / "todo.json"
        if todo_path.exists():
            try:
                content = todo_path.read_text(encoding="utf-8")
                from daiflow.services.task_service import sync_todos_from_file
                await sync_todos_from_file(ctx.db, ctx.entity_id, content)
            except Exception as e:
                logger.error("Failed to sync todo.json for task %s: %s", task.id, e)
        else:
            logger.warning("todo.json not found for task %s after generation", task.id)

        # Transition: plan_locked → todo_ready
        wf = TaskWorkflow(task, ctx.db)
        await wf.todos_ready()
        await ctx.db.commit()

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        todo_path = Path(ctx.task_dir) / "todo.json"
        return TODO_CHAT_PREFIX.format(todo_path=todo_path)


register_agent(TodoSplitAgent())
