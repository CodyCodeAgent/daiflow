"""CodyRunner — wraps AsyncCodyClient to satisfy AbstractAgentRunner.

This module owns the Cody-specific event translation (_chunk_to_event) that
previously lived in session_runner.py. SessionRunner now calls runner.stream()
and receives standard DaiFlow event dicts, with no Cody SDK dependency.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


def _chunk_to_event(chunk) -> dict | None:
    """Convert a Cody StreamChunk to a DaiFlow event dict.

    Returns None for chunks that should only be logged (compact), not yielded.
    For "done" chunks, the runner_session_id is attached so SessionRunner can
    store it in sessions.cody_session_id for multi-turn continuity.
    """
    t = chunk.type
    if t == "text_delta":
        return {"type": "text_delta", "content": chunk.content}
    elif t == "thinking":
        return {"type": "thinking", "content": chunk.content}
    elif t == "tool_call":
        return {
            "type": "tool_call",
            "tool_name": chunk.tool_name,
            "args": chunk.args if hasattr(chunk, "args") else {},
            "tool_call_id": chunk.tool_call_id if hasattr(chunk, "tool_call_id") else "",
        }
    elif t == "tool_result":
        return {
            "type": "tool_result",
            "content": chunk.content if hasattr(chunk, "content") else "",
            "tool_name": chunk.tool_name if hasattr(chunk, "tool_name") else "",
            "tool_call_id": chunk.tool_call_id if hasattr(chunk, "tool_call_id") else "",
        }
    elif t == "compact":
        return None
    elif t == "done":
        event: dict = {
            "type": "done",
            "usage": {
                "input_tokens": chunk.usage.input_tokens if hasattr(chunk, "usage") and chunk.usage else 0,
                "output_tokens": chunk.usage.output_tokens if hasattr(chunk, "usage") and chunk.usage else 0,
            },
            "runner_session_id": chunk.session_id if hasattr(chunk, "session_id") else None,
        }
        return event
    return None


class CodyRunner:
    """Adapter that wraps an AsyncCodyClient and translates its StreamChunk
    objects into standard DaiFlow event dicts.

    Usage::

        client = await build_cody_client(db, workdir, allowed_roots)
        runner = CodyRunner(client)
        async with runner:
            async for event in runner.stream(prompt, session_id=cody_sid):
                ...
    """

    def __init__(self, cody_client: Any) -> None:
        self._client = cody_client

    async def stream(
        self,
        prompt: "str | Any",
        session_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict]:
        kwargs: dict = {}
        if session_id:
            kwargs["session_id"] = session_id
        if cancel_event:
            kwargs["cancel_event"] = cancel_event

        async for chunk in self._client.stream(prompt, **kwargs):
            # Handle cancelled before _chunk_to_event (which returns None for unknown types)
            if chunk.type == "cancelled":
                yield {"type": "done", "cancelled": True}
                return
            event = _chunk_to_event(chunk)
            if event is None:
                yield {"type": "compact"}
                continue
            yield event

    async def __aenter__(self) -> "CodyRunner":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._client.__aexit__(exc_type, exc_val, exc_tb)
