"""Conversation agent: free-form project-aware chat."""

from daiflow.agents import AgentConfig, AgentContext, register_agent
from daiflow.session_runner import make_file_write_detector


class ConversationAgent(AgentConfig):
    agent_type = "conversation"
    chattable = True

    async def build_prompt(self, ctx: AgentContext) -> str:
        # Conversations are chat-only; this is never called for auto-run.
        return ""

    async def resolve_cody_session_id(self, ctx: AgentContext) -> str | None:
        from daiflow.models import Session
        session = await ctx.db.get(Session, ctx.session_id)
        if session and session.cody_session_id:
            return session.cody_session_id
        return None

    def build_artifact_detector(self, ctx: AgentContext):
        return make_file_write_detector(None, "code_updated")

    def chat_system_prefix(self, ctx: AgentContext) -> str | None:
        return (
            "You are a helpful AI assistant working on this project's codebase. "
            "You have access to the project's code and skill files. "
            "Help the user with any questions about the code, architecture, debugging, "
            "or implementation ideas.\n\n"
        )


register_agent(ConversationAgent())
