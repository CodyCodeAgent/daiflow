import asyncio
import inspect
import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import FILE_WRITE_TOOLS, LANGUAGE_INSTRUCTIONS, SESSIONS_DIR, safe_filename, utc_iso
from daiflow.models import Session, SessionStatus
from daiflow.runners.base import AbstractAgentRunner
from daiflow.ws_manager import WSManager, ws_manager as _default_ws_manager

logger = logging.getLogger(__name__)

# Default timeout for streaming operations (15 minutes)
STREAM_TIMEOUT_SECONDS = 900
# Max cached tool call args to prevent unbounded memory growth
MAX_TOOL_CALL_ARGS = 200
# Track sessions that have already received their system prefix.
# Lifetime matches Cody session context: both reset on server restart.
_chatted_sessions: set[str] = set()

# Active chat cancel events — keyed by chat channel (e.g. "chat:req_xxx")
_active_chats: dict[str, asyncio.Event] = {}


def cancel_chat(channel: str) -> bool:
    """Cancel an active chat by channel name. Returns True if found and cancelled."""
    event = _active_chats.get(channel)
    if event:
        event.set()
        return True
    return False


def _now():
    return datetime.now(timezone.utc)


def _now_iso():
    return utc_iso(_now())


def _log_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{safe_filename(session_id)}.jsonl"


def _append_log_sync(path: Path, data: str):
    """Sync file append (runs in thread pool)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(data)


async def append_log(session_id: str, event: dict):
    path = _log_path(session_id)
    data = json.dumps(event, ensure_ascii=False) + "\n"
    await asyncio.to_thread(_append_log_sync, path, data)


class _ToolCallTracker:
    """Tracks tool_call args and enriches tool_result events for file-write detection."""

    def __init__(self, max_cached: int = MAX_TOOL_CALL_ARGS):
        self._args: dict[str, dict] = {}
        self._max = max_cached

    def on_event(self, event: dict) -> dict | None:
        """Track a tool_call event's args for later enrichment.

        Returns a skill_loaded event if this is a read_skill call, else None.
        """
        if event["type"] == "tool_call":
            call_id = event.get("tool_call_id", "")
            if call_id:
                self._args[call_id] = event.get("args", {})
                if len(self._args) > self._max:
                    # Evict oldest half instead of clearing all
                    keys = list(self._args.keys())
                    for k in keys[:len(keys) // 2]:
                        del self._args[k]
            # Detect read_skill calls and emit skill_loaded event
            if event.get("tool_name") == "read_skill":
                skill_name = event.get("args", {}).get("skill_name", "")
                if skill_name:
                    return {"type": "skill_loaded", "skill_name": skill_name}
        return None

    def enrich(self, event: dict):
        """Enrich a tool_result event with cached args from its tool_call."""
        if event["type"] == "tool_result":
            call_id = event.get("tool_call_id", "")
            if call_id and call_id in self._args:
                event["args"] = self._args.pop(call_id)


class SessionRunner:
    """Unified AI task executor that wraps an AbstractAgentRunner.

    Supports any runner implementation (Cody, Claude Code, Cursor, etc.)
    through a unified streaming interface.

    Args:
        runner: Any AbstractAgentRunner implementation.
        ws_manager: WebSocket manager for publishing events. Defaults to the
            global singleton. Accept as parameter for testability.
    """

    def __init__(self, runner: AbstractAgentRunner, ws_manager: WSManager | None = None):
        self.runner = runner
        self._ws = ws_manager or _default_ws_manager
        self._last_runner_session_id: str | None = None
        self._tracker = _ToolCallTracker()

    @property
    def last_cody_session_id(self) -> str | None:
        """Alias for backward compatibility — returns the runner-native session ID."""
        return self._last_runner_session_id

    async def run(
        self,
        db: AsyncSession,
        session_id: str,
        prompt,
        extra_channels: list[str] | None = None,
        on_tool_result=None,
        cody_session_id: str | None = None,
        language: str | None = None,
        on_before_done=None,
    ):
        """Execute an AI task with full lifecycle management.

        Phases: prepare → stream → finalize (success or error).
        """
        if language and isinstance(prompt, str):
            prompt = prompt + LANGUAGE_INSTRUCTIONS.get(language, "")
        elif language and hasattr(prompt, "text"):
            prompt.text = prompt.text + LANGUAGE_INSTRUCTIONS.get(language, "")
        channel = f"session:{session_id}"

        await self._prepare(db, session_id, channel, prompt, extra_channels, cody_session_id)

        try:
            runner_sid, finished_at, done_ts = await self._stream(
                session_id, channel, prompt, extra_channels,
                on_tool_result, cody_session_id,
            )
            self._last_runner_session_id = runner_sid
            await self._finalize_success(
                db, session_id, channel, extra_channels,
                runner_sid, finished_at, done_ts, on_before_done,
            )
        except Exception as e:
            await self._finalize_error(
                db, session_id, channel, extra_channels, e, on_before_done,
            )

    async def _prepare(self, db, session_id, channel, prompt, extra_channels, cody_session_id):
        """Phase 1: Mark session RUNNING, log user message."""
        log_file = _log_path(session_id)
        if log_file.exists():
            await append_log(session_id, {"type": "run_boundary", "ts": _now_iso()})

        run_started_at = _now()
        run_values = {"status": SessionStatus.RUNNING, "started_at": run_started_at}
        if cody_session_id:
            run_values["cody_session_id"] = cody_session_id
        await db.execute(
            update(Session).where(Session.session_id == session_id).values(**run_values)
        )
        await db.commit()

        if extra_channels:
            for ch in extra_channels:
                await self._ws.publish(ch, {
                    "type": "session_status", "session_id": session_id,
                    "status": SessionStatus.RUNNING, "started_at": utc_iso(run_started_at),
                })

        log_content = prompt.text if hasattr(prompt, "text") else prompt
        user_event = {"type": "user_message", "content": log_content, "ts": _now_iso()}
        if hasattr(prompt, "images") and prompt.images:
            user_event["images"] = [img.filename for img in prompt.images]
        await append_log(session_id, user_event)

    async def _stream(self, session_id, channel, prompt, extra_channels, on_tool_result, cody_session_id):
        """Phase 2: Stream runner output, log events, publish to WS."""
        result_runner_session_id = None
        done_finished_at = _now()
        done_ts = _now_iso()

        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            async for event in self.runner.stream(prompt, session_id=cody_session_id):
                if event["type"] == "compact":
                    await append_log(session_id, {"type": "compact", "ts": _now_iso()})
                    continue

                event["ts"] = _now_iso()
                await append_log(session_id, event)

                if event["type"] == "done":
                    result_runner_session_id = event.get("runner_session_id")
                    done_finished_at = _now()
                    done_ts = event["ts"]
                    continue

                await self._ws.publish(channel, event)

                skill_event = self._tracker.on_event(event)
                if skill_event:
                    skill_event["ts"] = event["ts"]
                    await append_log(session_id, skill_event)
                    await self._ws.publish(channel, skill_event)
                    if extra_channels:
                        for ch in extra_channels:
                            await self._ws.publish(ch, {**skill_event, "session_id": session_id})
                if event["type"] == "tool_result" and on_tool_result:
                    self._tracker.enrich(event)
                    extra_event = await on_tool_result(event)
                    if extra_event:
                        await append_log(session_id, extra_event)
                        await self._ws.publish(channel, extra_event)

        return result_runner_session_id, done_finished_at, done_ts

    async def _finalize_success(self, db, session_id, channel, extra_channels,
                                runner_sid, finished_at, done_ts, on_before_done):
        """Phase 3a: Persist DONE status, run hook, publish terminal event."""
        await db.execute(
            update(Session).where(Session.session_id == session_id).values(
                status=SessionStatus.DONE, cody_session_id=runner_sid, finished_at=finished_at,
            )
        )
        await db.commit()

        if on_before_done:
            await on_before_done()

        status_event = {"type": "status_change", "status": SessionStatus.DONE, "ts": done_ts}
        await self._ws.publish(channel, status_event)
        await append_log(session_id, status_event)
        if extra_channels:
            for ch in extra_channels:
                await self._ws.publish(ch, {
                    "type": "session_status", "session_id": session_id,
                    "status": SessionStatus.DONE, "finished_at": utc_iso(finished_at), "ts": done_ts,
                })

    async def _finalize_error(self, db, session_id, channel, extra_channels, error, on_before_done):
        """Phase 3b: Persist FAILED status, run hook, publish terminal event."""
        error_msg = traceback.format_exc()
        error_event = {"type": "error", "content": str(error), "ts": _now_iso()}
        await append_log(session_id, error_event)

        failed_at = _now()
        await db.execute(
            update(Session).where(Session.session_id == session_id).values(
                status=SessionStatus.FAILED, error=error_msg, finished_at=failed_at,
            )
        )
        await db.commit()

        if on_before_done:
            try:
                await on_before_done()
            except Exception:
                logger.exception("on_before_done failed in error path")

        status_event = {"type": "status_change", "status": SessionStatus.FAILED, "error": str(error), "ts": _now_iso()}
        await self._ws.publish(channel, status_event)
        if extra_channels:
            for ch in extra_channels:
                await self._ws.publish(ch, {
                    "type": "session_status", "session_id": session_id,
                    "status": SessionStatus.FAILED, "error": str(error),
                    "finished_at": utc_iso(failed_at), "ts": utc_iso(failed_at),
                })


def _inject_file_context(file_paths: list[str], session_id: str) -> str:
    """Read files and prepend their contents as context for the prompt.

    Resolves paths relative to the entity directory derived from session_id.
    Supports both task sessions (task:{id}:...) and conversation sessions (conversation:{id}:...).
    """
    from daiflow.config import CONVERSATIONS_DIR, TASKS_DIR
    parts = session_id.split(":")
    entity_type = parts[0] if parts else ""
    entity_id = parts[1] if len(parts) >= 2 else ""
    if entity_type == "conversation" and entity_id:
        task_dir = CONVERSATIONS_DIR / entity_id
    elif entity_id:
        task_dir = TASKS_DIR / entity_id
    else:
        task_dir = None

    context_parts: list[str] = []
    for rel_path in file_paths[:20]:
        if not task_dir:
            continue
        full = task_dir / rel_path
        if not full.is_file():
            continue
        try:
            content = full.read_text(errors="replace")
            if len(content) > 50_000:
                content = content[:50_000] + "\n... (truncated)"
            context_parts.append(f"<file path=\"{rel_path}\">\n{content}\n</file>")
        except OSError:
            continue

    if not context_parts:
        return ""
    return "<context>\n" + "\n".join(context_parts) + "\n</context>\n\n"


def _inject_image_references(image_paths: list[str]) -> str:
    """Build a prompt prefix referencing image files."""
    refs = [f"[Attached image: {p}]" for p in image_paths[:10]]
    return "\n".join(refs) + "\n\n"


async def _persist_runner_session_id(session_id: str, runner_sid: str):
    """Save runner_session_id to Session DB record for multi-turn chat continuity.

    If no Session record exists (e.g. review stage which never runs SessionRunner.run()),
    creates a minimal record so subsequent chats can reuse the same Cody session.
    """
    try:
        from daiflow.database import get_background_db
        from daiflow.models import Session, SessionStatus
        async with get_background_db() as db:
            session = await db.get(Session, session_id)
            if session:
                session.cody_session_id = runner_sid
            else:
                # Parse task_id and type from business session_id (e.g. "task:{id}:review")
                parts = session_id.split(":")
                entity_type = parts[0] if parts else ""
                entity_id = parts[1] if len(parts) >= 2 else None
                stage = parts[2] if len(parts) >= 3 else "chat"
                task_id = entity_id if entity_type == "task" else None
                db.add(Session(
                    session_id=session_id,
                    task_id=task_id,
                    type=stage,
                    status=SessionStatus.DONE,
                    cody_session_id=runner_sid,
                ))
            await db.commit()
    except Exception:
        logger.debug("Failed to persist runner_session_id for %s", session_id, exc_info=True)


async def run_stage_chat(
    session_id: str,
    runner: AbstractAgentRunner,
    cody_session_id: str,
    message: str,
    on_tool_result=None,
    language: str | None = None,
    system_prefix: str | None = None,
    context_files: list[str] | None = None,
    images: list[str] | None = None,
    chat_channel: str | None = None,
):
    """Stage chat async generator. Yields raw event dicts.

    Used by WS handler. The caller sends events via ws.send_json.

    Args:
        session_id: DaiFlow business session ID (for log persistence)
        runner: Any AbstractAgentRunner implementation
        cody_session_id: Runner-native session ID for multi-turn continuity
        message: User message text
        on_tool_result: Optional callback for artifact detection
        language: Language code for instruction suffix
        system_prefix: Prepended to the first message of a session
        context_files: File paths (relative to task dir) to inject as context
        images: Image file paths to include (for multimodal runners)
        chat_channel: Chat channel name for cancel registration (e.g. "chat:req_xxx")
    """
    is_first = session_id not in _chatted_sessions
    if is_first:
        _chatted_sessions.add(session_id)
        if system_prefix:
            message = system_prefix + message

    if context_files:
        message = _inject_file_context(context_files, session_id) + message

    if images:
        message = _inject_image_references(images) + message

    # Log the original user message (without language instruction)
    user_event = {"type": "user_message", "content": message, "ts": _now_iso()}
    await append_log(session_id, user_event)

    # Language instruction only on the first message — Cody keeps session context
    ai_message = message
    if language and is_first:
        ai_message = message + LANGUAGE_INSTRUCTIONS.get(language, "")

    # Register cancel event for this chat
    cancel_event = asyncio.Event()
    if chat_channel:
        _active_chats[chat_channel] = cancel_event

    tracker = _ToolCallTracker()
    done_sent = False

    try:
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            stream_kwargs: dict = {"session_id": cody_session_id}
            # Pass cancel_event to runners that accept it (CodyRunner does)
            if "cancel_event" in inspect.signature(runner.stream).parameters:
                stream_kwargs["cancel_event"] = cancel_event
            async for event in runner.stream(ai_message, **stream_kwargs):
                if event["type"] == "compact":
                    continue

                event["ts"] = _now_iso()
                await append_log(session_id, event)

                if event["type"] == "done":
                    # Persist runner_session_id for multi-turn continuity
                    runner_sid = event.get("runner_session_id")
                    if runner_sid:
                        await _persist_runner_session_id(session_id, runner_sid)
                    done_sent = True
                    yield {"type": "done"}
                    return

                yield event

                skill_event = tracker.on_event(event)
                if skill_event:
                    skill_event["ts"] = event["ts"]
                    await append_log(session_id, skill_event)
                    yield skill_event
                if event["type"] == "tool_result" and on_tool_result:
                    tracker.enrich(event)
                    updated_event = await on_tool_result(event)
                    if updated_event:
                        await append_log(session_id, updated_event)
                        yield updated_event

    except Exception as e:
        error_event = {"type": "error", "content": str(e), "ts": _now_iso()}
        await append_log(session_id, error_event)
        yield error_event
    finally:
        if chat_channel:
            _active_chats.pop(chat_channel, None)
        # Only send done if not already sent in the try block (error/timeout paths)
        if not done_sent:
            done_event = {"type": "done", "ts": _now_iso()}
            await append_log(session_id, done_event)
            yield done_event


def _extract_file_path(event: dict) -> str:
    """Extract file path from a tool_result event's args."""
    args = event.get("args", {})
    if isinstance(args, dict):
        return args.get("path", args.get("file_path", ""))
    if isinstance(args, str):
        return args
    return ""


def make_file_write_detector(target_file: str | None, event_type: str, on_match=None):
    """Factory for on_tool_result callbacks that detect file writes.

    Args:
        target_file: Filename to match (e.g. "plan.md"), or None to match any write.
        event_type: Event type to emit (e.g. "plan_updated", "code_updated").
        on_match: Optional async callback(file_path) called on match, returns event content or None.
    """
    async def on_tool_result(event: dict):
        tool_name = event.get("tool_name", "")
        if tool_name not in FILE_WRITE_TOOLS:
            return None

        if target_file is None:
            # Match any file write
            content = await on_match(None) if on_match else None
            return {"type": event_type, "content": content}

        file_path = _extract_file_path(event)
        if file_path and file_path.endswith(target_file):
            content = await on_match(file_path) if on_match else None
            return {"type": event_type, "content": content}

        return None

    return on_tool_result
