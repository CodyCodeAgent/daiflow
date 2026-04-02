"""Single WebSocket endpoint with multiplexed channels.

Protocol:
  Client -> Server:
    {"action": "subscribe", "channel": "session:task:42:plan"}
    {"action": "unsubscribe", "channel": "session:task:42:plan"}
    {"action": "chat", "id": "req_1", "chat_path": "plan", "entity_id": "abc", "message": "..."}
    {"action": "tool_response", "call_id": "...", "decision": "accept|revert"}
    {"action": "ping"}

  Server -> Client:
    {"type": "subscribed", "channel": "..."}
    {"type": "pong"}
    {"channel": "...", "event": {...}}
    {"type": "error", "id": "...", "code": "...", "message": "..."}
"""

import asyncio
import logging
import subprocess

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from starlette.websockets import WebSocketState

from daiflow.config import HIGH_RISK_TOOLS
from daiflow.database import get_db_session
from daiflow.exceptions import DaiFlowError
from daiflow.models import Setting
from daiflow.services.chat_service import prepare_stage_chat
from daiflow.session_runner import run_stage_chat, cancel_chat
from daiflow.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_CONCURRENT_CHATS = 5

# Pending tool approval futures, keyed by call_id
_tool_approval_futures: dict[str, asyncio.Future] = {}


def _needs_review(tool_name: str, mode: str) -> bool:
    """Check if a tool needs post-execution review based on approval mode."""
    if mode == "auto":
        return False
    if mode == "all":
        return True
    if mode == "high_risk":
        return tool_name in HIGH_RISK_TOOLS
    return False


def _extract_file_path_from_event(event: dict) -> str:
    """Extract the file path from a tool event's args."""
    args = event.get("args", {})
    if isinstance(args, dict):
        return args.get("path", args.get("file_path", ""))
    return ""


async def _get_approval_mode() -> str:
    """Read tool_approval_mode from settings DB."""
    try:
        async with get_db_session() as db:
            result = await db.execute(
                select(Setting.value).where(Setting.key == "tool_approval_mode")
            )
            row = result.scalar_one_or_none()
            return row or "auto"
    except Exception:
        return "auto"


async def _handle_chat(ws: WebSocket, data: dict):
    """Handle a chat request in a background task."""
    req_id = data.get("id", "")
    stage = data.get("chat_path", "")
    entity_id = data.get("entity_id", "")
    message = data.get("message", "")
    context_files: list[str] = data.get("context_files") or []
    images: list[str] = data.get("images") or []
    channel = f"chat:{req_id}"

    if not all([req_id, stage, entity_id, message]):
        try:
            await ws.send_json({
                "type": "error",
                "id": req_id,
                "code": "invalid_request",
                "message": "Missing required fields: id, chat_path, entity_id, message",
            })
        except Exception:
            pass
        return

    approval_mode = await _get_approval_mode()

    try:
        async with get_db_session() as db:
            ctx = await prepare_stage_chat(db, stage, entity_id)

            async with ctx.cody_client:
                async for event in run_stage_chat(
                    ctx.session_id, ctx.cody_client, ctx.cody_session_id,
                    message, ctx.on_tool_result, language=ctx.language,
                    system_prefix=ctx.system_prefix,
                    context_files=context_files,
                    images=images,
                    chat_channel=channel,
                ):  # ctx.cody_client holds an AbstractAgentRunner
                    if ws.client_state != WebSocketState.CONNECTED:
                        return

                    await ws.send_json({"channel": channel, "event": event})

                    if (
                        event.get("type") == "tool_result"
                        and _needs_review(event.get("tool_name", ""), approval_mode)
                    ):
                        call_id = event.get("tool_call_id", "")
                        if call_id:
                            review_event = {
                                "type": "tool_review",
                                "tool_name": event.get("tool_name", ""),
                                "args": event.get("args", {}),
                                "content": event.get("content", ""),
                                "call_id": call_id,
                            }
                            await ws.send_json({"channel": channel, "event": review_event})

                            future: asyncio.Future = asyncio.get_event_loop().create_future()
                            _tool_approval_futures[call_id] = future
                            try:
                                decision = await asyncio.wait_for(future, timeout=300)
                                if decision == "revert":
                                    file_path = _extract_file_path_from_event(event)
                                    if file_path:
                                        try:
                                            subprocess.run(
                                                ["git", "checkout", "--", file_path],
                                                capture_output=True, timeout=10,
                                            )
                                            await ws.send_json({"channel": channel, "event": {
                                                "type": "tool_reverted",
                                                "call_id": call_id,
                                                "file_path": file_path,
                                            }})
                                        except Exception as re:
                                            logger.warning("Revert failed for %s: %s", file_path, re)
                            except asyncio.TimeoutError:
                                pass
                            finally:
                                _tool_approval_futures.pop(call_id, None)

    except DaiFlowError as e:
        try:
            await ws.send_json({
                "type": "error",
                "id": req_id,
                "code": "not_found" if e.status_code == 404 else "invalid_state",
                "message": str(e),
            })
        except Exception:
            pass
    except Exception as e:
        logger.exception("Chat error for request %s", req_id)
        try:
            await ws.send_json({
                "type": "error",
                "id": req_id,
                "code": "internal_error",
                "message": str(e),
            })
        except Exception:
            pass


@router.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    chat_tasks: list[asyncio.Task] = []

    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "ping":
                await ws.send_json({"type": "pong"})

            elif action == "subscribe":
                channel = data.get("channel", "")
                if channel:
                    ws_manager.subscribe(ws, channel)
                    await ws.send_json({"type": "subscribed", "channel": channel})

            elif action == "unsubscribe":
                channel = data.get("channel", "")
                if channel:
                    ws_manager.unsubscribe(ws, channel)

            elif action == "cancel_chat":
                req_id = data.get("id", "")
                if req_id:
                    cancel_chat(f"chat:{req_id}")

            elif action == "chat":
                chat_tasks = [t for t in chat_tasks if not t.done()]
                if len(chat_tasks) >= MAX_CONCURRENT_CHATS:
                    await ws.send_json({
                        "type": "error",
                        "id": data.get("id", ""),
                        "code": "rate_limited",
                        "message": f"Too many concurrent chats (max {MAX_CONCURRENT_CHATS})",
                    })
                else:
                    task = asyncio.create_task(_handle_chat(ws, data))
                    chat_tasks.append(task)

            elif action == "tool_response":
                call_id = data.get("call_id", "")
                decision = data.get("decision", "accept")
                future = _tool_approval_futures.get(call_id)
                if future and not future.done():
                    future.set_result(decision)

            else:
                await ws.send_json({
                    "type": "error",
                    "code": "unknown_action",
                    "message": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        ws_manager.disconnect(ws)
        for task in chat_tasks:
            if not task.done():
                task.cancel()
