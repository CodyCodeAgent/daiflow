"""AbstractAgentRunner protocol — the interface every runner must satisfy.

All runners yield DaiFlow event dicts so SessionRunner can consume them
uniformly, regardless of the underlying AI backend.

DaiFlow event dict schema
─────────────────────────
Required event types:
  {"type": "text_delta",  "content": str}
  {"type": "thinking",    "content": str}
  {"type": "tool_call",   "tool_name": str, "args": dict, "tool_call_id": str}
  {"type": "tool_result", "tool_name": str, "content": str, "tool_call_id": str,
                           "args": dict}          # args optional, enriched by tracker
  {"type": "done",        "usage": {"input_tokens": int, "output_tokens": int},
                           "runner_session_id": str | None}

Optional event types:
  {"type": "compact"}     # signals context compaction; logged only, not pushed to WS

The "done" event MUST be the last event yielded per stream() call.
runner_session_id in "done" is the backend-native session ID that enables
multi-turn conversation continuity (stored in sessions.cody_session_id).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


@runtime_checkable
class AbstractAgentRunner(Protocol):
    """Protocol that all agent runner implementations must satisfy.

    Implementations are async context managers — use `async with runner:` to
    ensure proper resource cleanup (subprocess teardown, SDK client close, etc.).
    """

    async def stream(
        self,
        prompt: "str | Any",
        session_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """Stream an AI task and yield DaiFlow event dicts.

        Args:
            prompt: The prompt to send. Either a plain string or a
                MultimodalPrompt-like object with a .text attribute and
                optional .images list (Cody SDK format; other runners
                will coerce to plain text automatically).
            session_id: Backend-native session ID for multi-turn continuity.
                Pass the value stored in sessions.cody_session_id from a
                prior run. None starts a fresh session.

        Yields:
            DaiFlow event dicts as described in the module docstring.
            The "done" event is always the last one yielded.
        """
        ...

    async def __aenter__(self) -> "AbstractAgentRunner":
        ...

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        ...
