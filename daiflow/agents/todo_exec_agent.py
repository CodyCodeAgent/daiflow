"""Todo-exec agent: implements a single todo item."""

import json
import logging
from pathlib import Path

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.prompts import TODO_EXECUTE_PROMPT_TEMPLATE
from daiflow.services.cody_service import append_path_boundary
from daiflow.session_runner import make_file_write_detector

logger = logging.getLogger(__name__)


class TodoExecAgent(AgentConfig):
    agent_type = "todo_exec"
    chattable = True

    async def build_prompt(self, ctx: AgentContext) -> str:
        from sqlalchemy import select
        from daiflow.models import Todo, TodoStatus

        todo = ctx.todo
        task_dir = Path(ctx.task_dir)

        # Collect completed todos for context
        done_todos: list = []
        if ctx.db is not None:
            result = await ctx.db.execute(
                select(Todo).where(
                    Todo.task_id == todo.task_id,
                    Todo.seq < todo.seq,
                    Todo.status == TodoStatus.DONE,
                ).order_by(Todo.seq)
            )
            done_todos = result.scalars().all()

        completed_lines = [f"- #{t.seq:03d} ✅ {t.title}" for t in done_todos]
        completed_context = (
            "## Completed Todos (already on disk, do NOT redo)\n"
            + "\n".join(completed_lines) + "\n\n"
        ) if completed_lines else ""

        text = TODO_EXECUTE_PROMPT_TEMPLATE.format(
            seq=todo.seq,
            title=todo.title,
            description=todo.description or "(none)",
            completed_context=completed_context,
        )
        return append_path_boundary(text, ctx.task_dir, ctx.allowed_roots)

    def build_artifact_detector(self, ctx: AgentContext):
        return make_file_write_detector(None, "code_updated")

    async def on_complete(self, ctx: AgentContext) -> None:
        from daiflow.models import Todo, SessionStatus
        from daiflow.services.git_service import get_head_hash
        from daiflow.workflow import TodoWorkflow

        # Re-fetch todo from DB in case it was modified/deleted during execution
        todo = await ctx.db.get(Todo, ctx.todo.id)
        if not todo:
            logger.warning("Todo %s no longer exists, skipping on_complete", ctx.todo.id)
            return

        # Record HEAD hash after execution
        head_after: dict[str, str] = {}
        for root in ctx.allowed_roots:
            try:
                head_after[root] = await get_head_hash(root)
            except Exception:
                pass
        todo.commit_after = json.dumps(head_after)

        # Capture cody_session_id for future chat
        from daiflow.models import Session
        session_rec = await ctx.db.get(Session, ctx.session_id)
        if session_rec and session_rec.cody_session_id:
            todo.cody_session_id = session_rec.cody_session_id

        # Transition: running → done or running → failed
        succeeded = session_rec and session_rec.status == SessionStatus.DONE
        todo_wf = TodoWorkflow(todo, ctx.db)
        if succeeded:
            await todo_wf.complete()
        else:
            await todo_wf.fail()
        await ctx.db.commit()


register_agent(TodoExecAgent())
