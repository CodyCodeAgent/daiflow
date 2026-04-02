"""CursorRunner — wraps the Cursor Agent CLI as a subprocess.

Uses `agent -p --force --trust --output-format stream-json` for headless
non-interactive execution. Reads NDJSON events from stdout.

Session continuity via `--resume session_id` CLI flag.

Event mapping from Cursor stream-json → DaiFlow:
  system (subtype=init)              → captures session_id
  assistant                          → text_delta (streaming text)
  tool_call (subtype=started)        → tool_call
  tool_call (subtype=completed)      → tool_result (with args from writeToolCall/readToolCall)
  result (subtype=success)           → done (with runner_session_id)

Requires the Cursor `agent` CLI to be installed and accessible in PATH.
Set CURSOR_API_KEY environment variable or pass api_key to __init__.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# asyncio StreamReader.readline() uses a 64KB limit; Cursor can emit longer NDJSON lines.
# We read in chunks and split by newline ourselves to avoid LimitOverrunError.
_MAX_LINE_BYTES = 10 * 1024 * 1024  # 10MB per line


async def _read_ndjson_lines(stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
    """Read NDJSON lines from stream without asyncio's 64KB readline limit."""
    buf = b""
    while True:
        if b"\n" in buf:
            line, _, buf = buf.partition(b"\n")
            yield line
            continue
        if len(buf) > _MAX_LINE_BYTES:
            # No newline in 10MB+ — discard head to avoid OOM (invalid/oversized Cursor output)
            logger.warning(
                "Cursor: line exceeded %s bytes, discarding head", _MAX_LINE_BYTES
            )
            buf = buf[_MAX_LINE_BYTES:]
            continue
        chunk = await stream.read(65536)
        if not chunk:
            if buf.strip():
                yield buf
            break
        buf += chunk


class CursorRunner:
    """Runner that spawns `agent` (Cursor Agent CLI) as a subprocess and reads its NDJSON output.

    Args:
        workdir: Working directory passed to --workspace.
        allowed_roots: Additional directories the agent may access (written into .cursorrules).
        api_key: Cursor API key (CURSOR_API_KEY env var used as fallback).
        model: Model name override (passed as --model if provided).
        max_turns: Maximum agentic turns (passed as --max-turns if provided).
        skill_dir: Path to DaiFlow skill directory — skills are converted to .cursorrules.
        mcp_servers: MCP server configs as (name, url, headers) tuples — written to .cursor/mcp.json.
    """

    def __init__(
        self,
        workdir: str,
        allowed_roots: list[str] | None = None,
        api_key: str = "",
        model: str | None = None,
        max_turns: int | None = None,
        skill_dir: str | None = None,
        mcp_servers: list[tuple[str, str, dict[str, str]]] | None = None,
    ) -> None:
        self._workdir = workdir
        self._allowed_roots = allowed_roots or []
        self._api_key = api_key or os.environ.get("CURSOR_API_KEY", "")
        self._model = model
        self._max_turns = max_turns
        self._skill_dir = skill_dir
        self._mcp_servers = mcp_servers or []
        self._proc: asyncio.subprocess.Process | None = None

    def _build_cmd(self, prompt: str, session_id: str | None) -> list[str]:
        cmd = [
            "agent", "-p",
            "--force",
            "--trust",
            "--output-format", "stream-json",
            "--stream-partial-output",
            "--workspace", self._workdir,
        ]
        if self._mcp_servers:
            cmd.append("--approve-mcps")
        if self._model:
            cmd += ["--model", self._model]
        if self._max_turns:
            cmd += ["--max-turns", str(self._max_turns)]
        if session_id:
            cmd += ["--resume", session_id]
        cmd.append(prompt)
        return cmd

    async def stream(
        self,
        prompt: "str | Any",
        session_id: str | None = None,
    ) -> AsyncIterator[dict]:
        prompt_text: str = prompt.text if hasattr(prompt, "text") else str(prompt)
        cmd = self._build_cmd(prompt_text, session_id)

        env = dict(os.environ)
        if self._api_key:
            env["CURSOR_API_KEY"] = self._api_key

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        result_session_id: str | None = None
        saw_terminal_success = False
        non_json_lines: list[str] = []
        stderr_text: str = ""
        # Track started tool calls by call_id so we can pair started→completed
        pending_tool_calls: dict[str, dict] = {}

        async def _read_stderr(proc: asyncio.subprocess.Process) -> str:
            if not proc.stderr:
                return ""
            data = await proc.stderr.read()
            return data.decode("utf-8", errors="replace").strip()

        stderr_task = asyncio.create_task(_read_stderr(self._proc))

        try:
            assert self._proc.stdout is not None
            async for raw_line in _read_ndjson_lines(self._proc.stdout):
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    non_json_lines.append(line[:1000])
                    logger.debug("Cursor: non-JSON line: %s", line[:200])
                    continue

                msg_type = msg.get("type", "")
                msg_subtype = msg.get("subtype", "")

                # Session init — capture session_id for continuity
                if msg_type == "system" and msg_subtype == "init":
                    result_session_id = msg.get("session_id")
                    continue

                # Streaming assistant text (plain string or nested content.content[].text)
                if msg_type == "assistant":
                    text = _extract_assistant_text(msg)
                    if text:
                        for event in _split_thinking(text):
                            yield event
                    continue

                # Tool call started
                if msg_type == "tool_call" and msg_subtype == "started":
                    call_id = msg.get("call_id", "")
                    tool_call_data = msg.get("tool_call", {})
                    # Extract tool name and args from the nested structure
                    tool_name, args = _extract_cursor_tool_info(tool_call_data, phase="started")
                    pending_tool_calls[call_id] = {"tool_name": tool_name, "args": args}
                    yield {
                        "type": "tool_call",
                        "tool_name": tool_name,
                        "args": args,
                        "tool_call_id": call_id,
                    }
                    continue

                # Tool call completed
                if msg_type == "tool_call" and msg_subtype == "completed":
                    call_id = msg.get("call_id", "")
                    tool_call_data = msg.get("tool_call", {})
                    tool_name, args = _extract_cursor_tool_info(
                        tool_call_data,
                        phase="completed",
                        pending=pending_tool_calls.get(call_id, {}),
                    )
                    pending_tool_calls.pop(call_id, None)
                    # Build result content string
                    result_content = _extract_cursor_result_content(tool_call_data)
                    yield {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "tool_call_id": call_id,
                        "content": result_content,
                        "args": args,  # pre-enriched; tracker.enrich() will be a no-op
                    }
                    continue

                # Terminal result
                if msg_type == "result" and msg_subtype == "success":
                    result_session_id = msg.get("session_id") or result_session_id
                    usage = msg.get("usage", {})
                    saw_terminal_success = True
                    yield {
                        "type": "done",
                        "usage": {
                            "input_tokens": usage.get("input_tokens", 0),
                            "output_tokens": usage.get("output_tokens", 0),
                        },
                        "runner_session_id": result_session_id,
                    }
                    return

                if msg_type == "result" and msg_subtype in ("error", "error_during_execution"):
                    error = msg.get("error", msg.get("result", "Unknown error"))
                    raise RuntimeError(str(error))

        finally:
            if self._proc and self._proc.returncode is None:
                try:
                    self._proc.terminate()
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                except Exception:
                    pass
            # Ensure stderr is always consumed to avoid task leaks
            try:
                stderr_text = await asyncio.wait_for(stderr_task, timeout=1)
            except Exception:
                stderr_task.cancel()
                stderr_text = ""

        # If we reached here without a success event, validate process result.
        rc = self._proc.returncode if self._proc else 1
        if not saw_terminal_success:
            # Cursor CLI sometimes prints plain text errors to stdout/stderr (non-JSON),
            # e.g. model availability/region restrictions.
            non_json_tail = "\n".join(non_json_lines[-5:]).strip()
            detail_parts = []
            if stderr_text:
                detail_parts.append(stderr_text)
            if non_json_tail:
                detail_parts.append(non_json_tail)
            detail = "\n".join(detail_parts).strip()
            if rc != 0 or detail:
                raise RuntimeError(
                    f"Cursor agent execution failed (exit={rc}). "
                    f"{detail[-3000:] if detail else 'No detailed error output.'}"
                )

        # Fallback done
        yield {
            "type": "done",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "runner_session_id": result_session_id,
        }

    async def __aenter__(self) -> "CursorRunner":
        _write_cursorrules(self._workdir, self._allowed_roots, self._skill_dir)
        _write_cursor_mcp_json(self._workdir, self._mcp_servers)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                pass
        self._proc = None


def _extract_cursor_tool_info(
    tool_call_data: dict,
    phase: str,
    pending: dict | None = None,
) -> tuple[str, dict]:
    """Extract (tool_name, args) from a Cursor tool_call event's nested structure.

    Handles three formats:
      1. Built-in tools: {"readToolCall": {"args": {...}}} (and other *ToolCall keys)
      2. MCP/custom tools: {"function": {"name": "tool_name", "arguments": "..."}}
      3. Fallback to pending data from the "started" event
    """
    # 1. Built-in tools: any key ending with "ToolCall"
    for key, value in tool_call_data.items():
        if key.endswith("ToolCall") and isinstance(value, dict):
            tool_name = _cursor_key_to_tool_name(key)
            args = value.get("args", {}) or {}
            return tool_name, args

    # 2. MCP / custom tools via "function" wrapper
    func = tool_call_data.get("function")
    if isinstance(func, dict):
        tool_name = func.get("name", "")
        raw_args = func.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except (json.JSONDecodeError, ValueError):
                args = {"raw": raw_args}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}
        return tool_name, args

    # 3. Fallback: check pending data from the "started" event
    if pending:
        return pending.get("tool_name", ""), pending.get("args", {})

    return "", {}


def _extract_cursor_result_content(tool_call_data: dict) -> str:
    """Extract a human-readable result string from a completed Cursor tool call."""
    # Built-in tools
    for key, value in tool_call_data.items():
        if key.endswith("ToolCall") and isinstance(value, dict):
            result = value.get("result", {})
            if isinstance(result, dict):
                success = result.get("success", {})
                if isinstance(success, dict):
                    return json.dumps(success)
                return str(result)
            return str(result)

    # MCP / function tools — result may be in "result" or "output" at top level
    func = tool_call_data.get("function")
    if isinstance(func, dict):
        result = func.get("result", func.get("output", ""))
        if isinstance(result, dict):
            return json.dumps(result)
        return str(result) if result else ""

    return ""


_CURSOR_TOOL_NAME_MAP = {
    "writeToolCall": "write_file",
    "editToolCall": "edit_file",
    "readToolCall": "read_file",
    "bashToolCall": "exec_command",
    "shellToolCall": "exec_command",
    "searchToolCall": "search",
    "grepToolCall": "grep",
    "lsToolCall": "list_dir",
    "globToolCall": "glob",
    "fetchToolCall": "url_fetch",
}


def _cursor_key_to_tool_name(key: str) -> str:
    """Map Cursor tool key names to DaiFlow tool names (matching FILE_WRITE_TOOLS)."""
    if key in _CURSOR_TOOL_NAME_MAP:
        return _CURSOR_TOOL_NAME_MAP[key]
    # Generic: strip "ToolCall" suffix and convert camelCase → snake_case
    name = key
    if name.endswith("ToolCall"):
        name = name[: -len("ToolCall")]
    return _camel_to_snake(name)


def _camel_to_snake(s: str) -> str:
    """Convert camelCase to snake_case."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s).lower()


_THINKING_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)


def _split_thinking(text: str) -> list[dict]:
    """Split assistant text into thinking and text_delta events.

    If the text contains <thinking>...</thinking> tags, extracts them as
    separate 'thinking' events; remaining text becomes 'text_delta'.
    """
    if "<thinking>" not in text:
        return [{"type": "text_delta", "content": text}]

    events: list[dict] = []
    last_end = 0
    for m in _THINKING_RE.finditer(text):
        before = text[last_end:m.start()]
        if before.strip():
            events.append({"type": "text_delta", "content": before})
        events.append({"type": "thinking", "content": m.group(1)})
        last_end = m.end()
    after = text[last_end:]
    if after.strip():
        events.append({"type": "text_delta", "content": after})
    return events or [{"type": "text_delta", "content": text}]


def _extract_assistant_text(msg: dict) -> str:
    """Extract plain text from Cursor assistant message (string or nested content blocks)."""
    # Plain string (e.g. "message": "hello")
    raw = msg.get("message")
    if isinstance(raw, str):
        return raw
    # Nested shape: message.content[] with type/text blocks
    if isinstance(raw, dict):
        content = raw.get("content")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text")
                    if isinstance(t, str):
                        parts.append(t)
            if parts:
                return "".join(parts)
    return ""


# ── .cursorrules generation ──


def _strip_yaml_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (---...---) from a markdown file."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text
    end = stripped.find("---", 3)
    if end == -1:
        return text
    after = stripped[end + 3:]
    return after.lstrip("\n")


def _read_skills(skill_dir: str) -> list[tuple[str, str]]:
    """Read all SKILL.md files from a DaiFlow skill directory.

    Returns list of (skill_name, body_without_frontmatter).
    """
    from pathlib import Path

    skills_path = Path(skill_dir)
    if not skills_path.exists():
        return []

    results = []
    for child in sorted(skills_path.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if skill_file.exists():
            raw = skill_file.read_text(encoding="utf-8")
            body = _strip_yaml_frontmatter(raw).strip()
            if body:
                results.append((child.name, body))
    return results


def _build_cursorrules_content(
    allowed_roots: list[str],
    skill_dir: str | None,
    workdir: str,
) -> str:
    """Build .cursorrules file content from allowed_roots and DaiFlow skills."""
    sections: list[str] = []

    # Workspace context
    extra_roots = [r for r in allowed_roots if r != workdir]
    if extra_roots:
        lines = ["## Allowed Workspace Roots", ""]
        lines.append(
            "You have access to the following additional directories beyond the primary workspace:"
        )
        lines.append("")
        for root in extra_roots:
            lines.append(f"- `{root}`")
        lines.append("")
        lines.append(
            "You may read and write files in these directories as needed."
        )
        sections.append("\n".join(lines))

    # Project knowledge (project.md)
    from pathlib import Path
    project_md = Path(workdir) / "project.md"
    if project_md.exists():
        content = project_md.read_text(encoding="utf-8").strip()
        if content:
            sections.append(f"## Project Knowledge\n\n{content}")

    # Skills
    if skill_dir:
        skills = _read_skills(skill_dir)
        for name, body in skills:
            sections.append(f"## Skill: {name}\n\n{body}")

    if not sections:
        return ""
    return "\n\n---\n\n".join(sections) + "\n"


def _write_cursorrules(
    workdir: str,
    allowed_roots: list[str],
    skill_dir: str | None,
) -> None:
    """Write a .cursorrules file into the workspace, merging allowed_roots and skills."""
    from pathlib import Path

    content = _build_cursorrules_content(allowed_roots, skill_dir, workdir)
    if not content:
        return

    rules_path = Path(workdir) / ".cursorrules"
    rules_path.write_text(content, encoding="utf-8")
    logger.debug("Wrote .cursorrules to %s (%d bytes)", rules_path, len(content))


def _write_cursor_mcp_json(
    workdir: str,
    mcp_servers: list[tuple[str, str, dict[str, str]]],
) -> None:
    """Write .cursor/mcp.json so the Cursor Agent CLI can use MCP servers.

    Merges with any existing .cursor/mcp.json (subprocess-format entries)
    rather than overwriting it.  DaiFlow HTTP entries win on name collision.
    """
    from pathlib import Path

    cursor_dir = Path(workdir) / ".cursor"
    mcp_path = cursor_dir / "mcp.json"

    # Load existing entries (subprocess-format MCPs)
    existing_servers: dict[str, dict] = {}
    if mcp_path.exists():
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8"))
            existing_servers = data.get("mcpServers", {})
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not parse existing .cursor/mcp.json — will overwrite")
            existing_servers = {}

    if not mcp_servers and not existing_servers:
        return

    # Build merged config: existing first, then DaiFlow HTTP entries (which override on collision)
    merged: dict[str, dict] = dict(existing_servers)
    for name, url, headers in mcp_servers:
        entry: dict[str, Any] = {"url": url}
        if headers:
            entry["headers"] = headers
        merged[name] = entry

    if not merged:
        return

    mcp_json = {"mcpServers": merged}
    cursor_dir.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(json.dumps(mcp_json, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.debug(
        "Wrote .cursor/mcp.json to %s (%d total servers, %d from DaiFlow, %d preserved)",
        mcp_path, len(merged), len(mcp_servers), len(existing_servers),
    )
