"""ClaudeCodeRunner — wraps Claude Code CLI as a subprocess (direct protocol, no SDK).

Uses the same pattern as CursorRunner: spawn `claude` with --output-format stream-json
and --input-format stream-json, send initialize + user message via stdin, read NDJSON
from stdout. Session continuity via --resume session_id.

Event mapping from Claude Code stream-json → DaiFlow:
  stream_event content_block_delta (text_delta)  → text_delta
  stream_event content_block_start (tool_use)   → tool_call (buffered until stop)
  stream_event content_block_delta (input_json) → appended to tool_call args buffer
  stream_event content_block_stop (tool_use)    → flush tool_call + synthetic tool_result
  result (subtype=success)                      → done (with runner_session_id)

Requires Claude Code CLI to be installed (e.g. npm install -g @anthropic-ai/claude-code).
Set ANTHROPIC_API_KEY or pass api_key to __init__.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# Default tools allowed (matches SDK / CLI default set)
_CLAUDE_ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "Bash", "MultiEdit", "NotebookEdit", "TodoRead", "TodoWrite",
]
# Max single NDJSON line size to avoid OOM
_MAX_LINE_BYTES = 10 * 1024 * 1024  # 10MB


def _find_cli() -> str:
    """Resolve Claude Code CLI binary path."""
    if path := __import__("shutil").which("claude"):
        return path
    for loc in [
        Path.home() / ".npm-global/bin/claude",
        Path("/usr/local/bin/claude"),
        Path.home() / ".local/bin/claude",
        Path.home() / "node_modules/.bin/claude",
        Path.home() / ".yarn/bin/claude",
        Path.home() / ".claude/local/claude",
    ]:
        if loc.exists() and loc.is_file():
            return str(loc)
    raise FileNotFoundError(
        "Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
    )


async def _read_ndjson_lines(stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
    """Read NDJSON lines from stream without asyncio's 64KB readline limit."""
    buf = b""
    while True:
        if b"\n" in buf:
            line, _, buf = buf.partition(b"\n")
            yield line
            continue
        if len(buf) > _MAX_LINE_BYTES:
            logger.warning(
                "Claude Code: line exceeded %s bytes, discarding head", _MAX_LINE_BYTES
            )
            buf = buf[_MAX_LINE_BYTES:]
            continue
        chunk = await stream.read(65536)
        if not chunk:
            if buf.strip():
                yield buf
            break
        buf += chunk


class ClaudeCodeRunner:
    """Runner that spawns Claude Code CLI as a subprocess and talks via stdin/stdout NDJSON.

    Args:
        workdir: Working directory (cwd for the subprocess).
        allowed_roots: Additional directories the agent may access (--add-dir each).
        api_key: Anthropic API key (ANTHROPIC_API_KEY env used as fallback when empty).
        model: Model name override (e.g. claude-sonnet-4-6).
        max_turns: Maximum agentic turns.
    """

    def __init__(
        self,
        workdir: str,
        allowed_roots: list[str] | None = None,
        api_key: str = "",
        model: str | None = None,
        max_turns: int | None = None,
    ) -> None:
        self._workdir = workdir
        self._allowed_roots = list(allowed_roots or [])
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._max_turns = max_turns
        self._proc: asyncio.subprocess.Process | None = None

    def _build_cmd(self, session_id: str | None) -> list[str]:
        """Build CLI command (no prompt; prompt is sent via stdin)."""
        cli_path = _find_cli()
        cmd = [
            cli_path,
            "--output-format", "stream-json",
            "--verbose",
            "--input-format", "stream-json",
            "--system-prompt", "",
            "--allowedTools", ",".join(_CLAUDE_ALLOWED_TOOLS),
            "--permission-mode", "bypassPermissions",
            "--include-partial-messages",
        ]
        if self._model:
            cmd += ["--model", self._model]
        if self._max_turns is not None:
            cmd += ["--max-turns", str(self._max_turns)]
        if session_id:
            cmd += ["--resume", session_id]
        for d in self._allowed_roots:
            if d != self._workdir:
                cmd += ["--add-dir", str(d)]
        return cmd

    async def stream(
        self,
        prompt: str | Any,
        session_id: str | None = None,
    ) -> AsyncIterator[dict]:
        prompt_text: str = prompt.text if hasattr(prompt, "text") else str(prompt)
        cmd = self._build_cmd(session_id)

        env = dict(os.environ)
        if self._api_key:
            env["ANTHROPIC_API_KEY"] = self._api_key
        env["PWD"] = self._workdir

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workdir,
            env=env,
        )

        init_request_id = f"req_1_{uuid.uuid4().hex[:8]}"
        init_done = False
        result_session_id: str | None = None
        tool_buffers: dict[int, dict] = {}  # index -> {tool_name, tool_call_id, args_json}

        async def write_stdin():
            if self._proc is None or self._proc.stdin is None:
                return
            try:
                # Send initialize control request
                control_request = {
                    "type": "control_request",
                    "request_id": init_request_id,
                    "request": {"subtype": "initialize", "hooks": None},
                }
                self._proc.stdin.write((json.dumps(control_request) + "\n").encode("utf-8"))
                # Send user message (same format as SDK)
                user_msg = {
                    "type": "user",
                    "session_id": "",
                    "message": {"role": "user", "content": prompt_text},
                    "parent_tool_use_id": None,
                }
                self._proc.stdin.write((json.dumps(user_msg) + "\n").encode("utf-8"))
                await self._proc.stdin.drain()
                # Keep stdin open so we can reply to control_request from CLI if needed
            except Exception as e:
                logger.debug("Claude Code stdin write error: %s", e)

        # Start writing stdin in background so we can read stdout immediately
        write_task = asyncio.create_task(write_stdin())

        try:
            assert self._proc.stdout is not None
            async for raw_line in _read_ndjson_lines(self._proc.stdout):
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Claude Code: non-JSON line: %s", line[:200])
                    continue

                msg_type = msg.get("type", "")

                # Initialize response — just mark done
                if msg_type == "control_response":
                    resp = msg.get("response", {}) or {}
                    if resp.get("request_id") == init_request_id:
                        init_done = True
                    continue

                # CLI sent a control request (e.g. MCP) — reply so it doesn't block
                if msg_type == "control_request":
                    req_id = msg.get("request_id", "")
                    err_response = {
                        "type": "control_response",
                        "response": {
                            "request_id": req_id,
                            "subtype": "error",
                            "error": "Not implemented (direct CLI mode)",
                        },
                    }
                    if self._proc and self._proc.stdin:
                        try:
                            self._proc.stdin.write(
                                (json.dumps(err_response) + "\n").encode("utf-8")
                            )
                            await self._proc.stdin.drain()
                        except Exception:
                            pass
                    continue

                # Stream event — map to DaiFlow events (same as previous SDK-based mapping)
                if msg_type == "stream_event":
                    event = msg.get("event") or {}
                    event_type = event.get("type")

                    if event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        delta_type = delta.get("type")
                        if delta_type == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield {"type": "text_delta", "content": text}
                        elif delta_type == "input_json_delta":
                            idx = event.get("index")
                            partial = delta.get("partial_json", "") or ""
                            if idx is not None and idx in tool_buffers:
                                tool_buffers[idx]["args_json"] += partial

                    elif event_type == "content_block_start":
                        block = event.get("content_block") or {}
                        idx = event.get("index")
                        if block.get("type") == "tool_use" and idx is not None:
                            tool_buffers[idx] = {
                                "tool_name": block.get("name", ""),
                                "tool_call_id": block.get("id", ""),
                                "args_json": "",
                            }

                    elif event_type == "content_block_stop":
                        idx = event.get("index")
                        if idx is not None and idx in tool_buffers:
                            buf = tool_buffers.pop(idx)
                            args_json = buf.get("args_json", "")
                            try:
                                args = json.loads(args_json) if args_json else {}
                            except json.JSONDecodeError:
                                args = {"raw": args_json}
                            tool_name = buf.get("tool_name", "")
                            tool_call_id = buf.get("tool_call_id", "")
                            yield {
                                "type": "tool_call",
                                "tool_name": tool_name,
                                "args": args,
                                "tool_call_id": tool_call_id,
                            }
                            yield {
                                "type": "tool_result",
                                "tool_name": tool_name,
                                "tool_call_id": tool_call_id,
                                "content": "",
                                "args": args,
                            }
                    continue

                # Terminal result
                if msg_type == "result":
                    subtype = msg.get("subtype", "")
                    if subtype == "success":
                        result_session_id = msg.get("session_id") or result_session_id
                        usage = msg.get("usage") or {}
                        yield {
                            "type": "done",
                            "usage": {
                                "input_tokens": usage.get("input_tokens", 0),
                                "output_tokens": usage.get("output_tokens", 0),
                            },
                            "runner_session_id": result_session_id,
                        }
                        return
                    if subtype in ("error", "error_during_execution"):
                        err = msg.get("error", msg.get("result", "Unknown error"))
                        yield {"type": "error", "content": str(err)}
                        yield {
                            "type": "done",
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                            "runner_session_id": result_session_id,
                        }
                        return

        finally:
            await write_task  # ensure stdin was written
            if self._proc and self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
            if self._proc and self._proc.returncode is None:
                try:
                    self._proc.terminate()
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                except Exception:
                    pass

        # If process exited with error before we got a result, raise with stderr
        if self._proc and self._proc.returncode is not None and self._proc.returncode != 0:
            stderr_b = b""
            if self._proc.stderr:
                try:
                    stderr_b = await self._proc.stderr.read()
                except Exception:
                    pass
            stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
            hint = (
                " Claude Code CLI 子进程异常退出。请检查：1) 是否已安装并可用 `claude` 命令（npm install -g @anthropic-ai/claude-code）；"
                " 2) ANTHROPIC_API_KEY 或 Runner 配置中的 api_key 是否有效；"
                " 3) 在终端直接运行 `claude` 查看 stderr 具体错误。"
            )
            raise RuntimeError(
                f"Command failed with exit code {self._proc.returncode}. {hint}"
                + (f"\nStderr: {stderr_text}" if stderr_text else "")
            )

        # Fallback done
        yield {
            "type": "done",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "runner_session_id": result_session_id,
        }

    async def __aenter__(self) -> "ClaudeCodeRunner":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                pass
        self._proc = None
