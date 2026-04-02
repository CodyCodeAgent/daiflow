"""Tests for CursorRunner — MCP integration, tool parsing, skill→.cursorrules, allowed_roots."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from daiflow.runners.cursor_runner import (
    CursorRunner,
    _build_cursorrules_content,
    _camel_to_snake,
    _cursor_key_to_tool_name,
    _extract_cursor_result_content,
    _extract_cursor_tool_info,
    _read_skills,
    _strip_yaml_frontmatter,
    _write_cursor_mcp_json,
    _write_cursorrules,
)


# ── YAML frontmatter stripping ──


class TestStripYamlFrontmatter:
    def test_no_frontmatter(self):
        assert _strip_yaml_frontmatter("Hello world") == "Hello world"

    def test_with_frontmatter(self):
        text = "---\ntitle: foo\nuser-invocable: false\n---\n\n# Body\nContent here"
        result = _strip_yaml_frontmatter(text)
        assert result.startswith("# Body")
        assert "title: foo" not in result

    def test_only_frontmatter(self):
        text = "---\nkey: val\n---\n"
        result = _strip_yaml_frontmatter(text)
        assert result == ""

    def test_no_closing_fence(self):
        text = "---\nkey: val\nno closing"
        assert _strip_yaml_frontmatter(text) == text

    def test_leading_whitespace(self):
        text = "  \n---\nkey: val\n---\nBody"
        result = _strip_yaml_frontmatter(text)
        assert "Body" in result


# ── Skill reading ──


class TestReadSkills:
    def test_empty_dir(self, tmp_path):
        assert _read_skills(str(tmp_path)) == []

    def test_nonexistent_dir(self):
        assert _read_skills("/nonexistent/path/12345") == []

    def test_reads_skill_files(self, tmp_path):
        skill_a = tmp_path / "api-interaction"
        skill_a.mkdir()
        (skill_a / "SKILL.md").write_text(
            "---\ntitle: API Interaction\nuser-invocable: false\n---\n\n# API Overview\nREST endpoints..."
        )

        skill_b = tmp_path / "backend-structure"
        skill_b.mkdir()
        (skill_b / "SKILL.md").write_text("# Backend\nService layer details")

        results = _read_skills(str(tmp_path))
        assert len(results) == 2
        assert results[0][0] == "api-interaction"
        assert "API Overview" in results[0][1]
        assert "title:" not in results[0][1]
        assert results[1][0] == "backend-structure"
        assert "Backend" in results[1][1]

    def test_skips_empty_skills(self, tmp_path):
        skill = tmp_path / "empty-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\ntitle: Empty\n---\n")

        results = _read_skills(str(tmp_path))
        assert len(results) == 0

    def test_skips_non_directories(self, tmp_path):
        (tmp_path / "README.md").write_text("Not a skill")
        assert _read_skills(str(tmp_path)) == []


# ── .cursorrules content building ──


class TestBuildCursorrulesContent:
    def test_empty_inputs(self, tmp_path):
        result = _build_cursorrules_content([], None, str(tmp_path))
        assert result == ""

    def test_allowed_roots_only(self, tmp_path):
        roots = [str(tmp_path), "/extra/repo1", "/extra/repo2"]
        result = _build_cursorrules_content(roots, None, str(tmp_path))
        assert "/extra/repo1" in result
        assert "/extra/repo2" in result
        assert str(tmp_path) not in result.split("## Allowed Workspace Roots")[1].split("---")[0]

    def test_skills_only(self, tmp_path):
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        s = skill_dir / "my-skill"
        s.mkdir()
        (s / "SKILL.md").write_text("---\ntitle: Test\n---\n\n# Test Skill\nDetails")

        result = _build_cursorrules_content([], str(skill_dir), str(tmp_path))
        assert "## Skill: my-skill" in result
        assert "# Test Skill" in result

    def test_project_md_included(self, tmp_path):
        (tmp_path / "project.md").write_text("# Project Index\nOverview of project")
        result = _build_cursorrules_content([str(tmp_path)], None, str(tmp_path))
        assert "## Project Knowledge" in result
        assert "Project Index" in result

    def test_combined(self, tmp_path):
        (tmp_path / "project.md").write_text("# Project")
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        s = skill_dir / "test"
        s.mkdir()
        (s / "SKILL.md").write_text("# Skill Body")
        roots = [str(tmp_path), "/repo/frontend"]

        result = _build_cursorrules_content(roots, str(skill_dir), str(tmp_path))
        assert "## Allowed Workspace Roots" in result
        assert "## Project Knowledge" in result
        assert "## Skill: test" in result
        assert "---" in result


# ── .cursorrules file writing ──


class TestWriteCursorrules:
    def test_writes_file(self, tmp_path):
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        s = skill_dir / "foo"
        s.mkdir()
        (s / "SKILL.md").write_text("# Foo Skill\nContent")

        _write_cursorrules(str(tmp_path), [str(tmp_path), "/extra"], str(skill_dir))

        rules = (tmp_path / ".cursorrules").read_text()
        assert "/extra" in rules
        assert "Foo Skill" in rules

    def test_no_write_when_empty(self, tmp_path):
        _write_cursorrules(str(tmp_path), [], None)
        assert not (tmp_path / ".cursorrules").exists()


# ── .cursor/mcp.json writing ──


class TestWriteCursorMcpJson:
    def test_writes_mcp_json(self, tmp_path):
        servers = [
            ("my-server", "https://mcp.example.com/mcp", {"X-Auth-Token": "tok123"}),
            ("custom", "https://mcp.example.com/sse", {}),
        ]
        _write_cursor_mcp_json(str(tmp_path), servers)

        mcp_path = tmp_path / ".cursor" / "mcp.json"
        assert mcp_path.exists()
        data = json.loads(mcp_path.read_text())
        assert "mcpServers" in data
        assert "my-server" in data["mcpServers"]
        assert data["mcpServers"]["my-server"]["url"] == "https://mcp.example.com/mcp"
        assert data["mcpServers"]["my-server"]["headers"]["X-Auth-Token"] == "tok123"
        assert "custom" in data["mcpServers"]
        assert "headers" not in data["mcpServers"]["custom"]

    def test_no_write_when_empty(self, tmp_path):
        _write_cursor_mcp_json(str(tmp_path), [])
        assert not (tmp_path / ".cursor" / "mcp.json").exists()

    def test_creates_cursor_dir(self, tmp_path):
        _write_cursor_mcp_json(str(tmp_path), [("s", "http://x", {})])
        assert (tmp_path / ".cursor").is_dir()


# ── Tool info extraction (builtin + MCP/function) ──


class TestExtractCursorToolInfo:
    def test_builtin_read(self):
        data = {"readToolCall": {"args": {"path": "file.txt"}}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "read_file"
        assert args == {"path": "file.txt"}

    def test_builtin_write(self):
        data = {"writeToolCall": {"args": {"path": "out.txt", "fileText": "hello"}}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "write_file"
        assert args["path"] == "out.txt"

    def test_builtin_edit(self):
        data = {"editToolCall": {"args": {"path": "f.py"}}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "edit_file"

    def test_builtin_shell(self):
        data = {"shellToolCall": {"args": {"command": "ls -la"}}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "exec_command"

    def test_builtin_grep(self):
        data = {"grepToolCall": {"args": {"pattern": "TODO"}}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "grep"

    def test_builtin_ls(self):
        data = {"lsToolCall": {"args": {"path": "."}}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "list_dir"

    def test_unknown_builtin_uses_snake_case(self):
        data = {"myCustomToolCall": {"args": {"x": 1}}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "my_custom"
        assert args == {"x": 1}

    def test_mcp_function_with_dict_args(self):
        data = {"function": {"name": "fetch-doc", "arguments": {"url": "https://doc.example.com"}}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "fetch-doc"
        assert args == {"url": "https://doc.example.com"}

    def test_mcp_function_with_string_args(self):
        data = {"function": {"name": "mcp_tool", "arguments": '{"key": "val"}'}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "mcp_tool"
        assert args == {"key": "val"}

    def test_mcp_function_with_invalid_json_args(self):
        data = {"function": {"name": "tool", "arguments": "not-json"}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "tool"
        assert args == {"raw": "not-json"}

    def test_mcp_function_with_empty_args(self):
        data = {"function": {"name": "ping"}}
        name, args = _extract_cursor_tool_info(data, phase="started")
        assert name == "ping"
        assert args == {}

    def test_fallback_to_pending(self):
        data = {}
        pending = {"tool_name": "cached_tool", "args": {"a": 1}}
        name, args = _extract_cursor_tool_info(data, phase="completed", pending=pending)
        assert name == "cached_tool"
        assert args == {"a": 1}

    def test_empty_fallback(self):
        name, args = _extract_cursor_tool_info({}, phase="started")
        assert name == ""
        assert args == {}


# ── Tool result content extraction ──


class TestExtractCursorResultContent:
    def test_builtin_tool_success(self):
        data = {"readToolCall": {"result": {"success": {"content": "file data", "totalLines": 10}}}}
        result = _extract_cursor_result_content(data)
        parsed = json.loads(result)
        assert parsed["content"] == "file data"

    def test_builtin_tool_non_dict_result(self):
        data = {"bashToolCall": {"result": "output text"}}
        result = _extract_cursor_result_content(data)
        assert result == "output text"

    def test_mcp_function_result(self):
        data = {"function": {"name": "fetch-doc", "result": {"title": "Doc", "body": "content"}}}
        result = _extract_cursor_result_content(data)
        parsed = json.loads(result)
        assert parsed["title"] == "Doc"

    def test_mcp_function_string_result(self):
        data = {"function": {"name": "tool", "result": "plain text"}}
        result = _extract_cursor_result_content(data)
        assert result == "plain text"

    def test_empty_data(self):
        assert _extract_cursor_result_content({}) == ""


# ── camelCase → snake_case ──


class TestCamelToSnake:
    def test_simple(self):
        assert _camel_to_snake("myCustom") == "my_custom"

    def test_multiple_words(self):
        assert _camel_to_snake("readFileContent") == "read_file_content"

    def test_already_lower(self):
        assert _camel_to_snake("read") == "read"

    def test_single_char(self):
        assert _camel_to_snake("A") == "a"


# ── Tool name mapping ──


class TestCursorKeyToToolName:
    def test_known_keys(self):
        assert _cursor_key_to_tool_name("writeToolCall") == "write_file"
        assert _cursor_key_to_tool_name("editToolCall") == "edit_file"
        assert _cursor_key_to_tool_name("readToolCall") == "read_file"
        assert _cursor_key_to_tool_name("bashToolCall") == "exec_command"
        assert _cursor_key_to_tool_name("shellToolCall") == "exec_command"
        assert _cursor_key_to_tool_name("searchToolCall") == "search"
        assert _cursor_key_to_tool_name("grepToolCall") == "grep"
        assert _cursor_key_to_tool_name("lsToolCall") == "list_dir"
        assert _cursor_key_to_tool_name("globToolCall") == "glob"
        assert _cursor_key_to_tool_name("fetchToolCall") == "url_fetch"

    def test_unknown_strips_suffix(self):
        assert _cursor_key_to_tool_name("notebookEditToolCall") == "notebook_edit"


# ── CursorRunner.__init__ ──


class TestCursorRunnerInit:
    def test_defaults(self):
        runner = CursorRunner(workdir="/w")
        assert runner._workdir == "/w"
        assert runner._allowed_roots == []
        assert runner._skill_dir is None
        assert runner._mcp_servers == []

    def test_with_all_params(self):
        servers = [("my-srv", "https://mcp.example.com/mcp", {"X-Token": "t"})]
        runner = CursorRunner(
            workdir="/w",
            allowed_roots=["/a", "/b"],
            skill_dir="/skills",
            mcp_servers=servers,
        )
        assert runner._allowed_roots == ["/a", "/b"]
        assert runner._skill_dir == "/skills"
        assert runner._mcp_servers == servers


# ── CursorRunner.__aenter__ writes .cursorrules + .cursor/mcp.json ──


class TestCursorRunnerAenter:
    @pytest.mark.asyncio
    async def test_aenter_writes_cursorrules(self, tmp_path):
        skill_dir = tmp_path / ".cody" / "skills"
        skill_dir.mkdir(parents=True)
        s = skill_dir / "test-skill"
        s.mkdir()
        (s / "SKILL.md").write_text("---\ntitle: TS\n---\n\n# Test\nBody")

        runner = CursorRunner(
            workdir=str(tmp_path),
            allowed_roots=[str(tmp_path), "/extra/repo"],
            skill_dir=str(skill_dir),
        )
        async with runner:
            rules_file = tmp_path / ".cursorrules"
            assert rules_file.exists()
            content = rules_file.read_text()
            assert "/extra/repo" in content
            assert "## Skill: test-skill" in content

    @pytest.mark.asyncio
    async def test_aenter_writes_mcp_json(self, tmp_path):
        servers = [("my-srv", "https://mcp.example.com/mcp", {"X-Auth-Token": "token"})]
        runner = CursorRunner(workdir=str(tmp_path), mcp_servers=servers)
        async with runner:
            mcp_path = tmp_path / ".cursor" / "mcp.json"
            assert mcp_path.exists()
            data = json.loads(mcp_path.read_text())
            assert data["mcpServers"]["my-srv"]["url"] == "https://mcp.example.com/mcp"

    @pytest.mark.asyncio
    async def test_aenter_no_mcp_when_empty(self, tmp_path):
        runner = CursorRunner(workdir=str(tmp_path))
        async with runner:
            assert not (tmp_path / ".cursor" / "mcp.json").exists()


# ── CursorRunner._build_cmd ──


class TestBuildCmd:
    def test_basic_cmd(self):
        runner = CursorRunner(workdir="/w")
        cmd = runner._build_cmd("do stuff", None)
        assert cmd[:2] == ["agent", "-p"]
        assert "--workspace" in cmd
        assert cmd[cmd.index("--workspace") + 1] == "/w"
        assert "--approve-mcps" not in cmd
        assert cmd[-1] == "do stuff"

    def test_with_model_and_max_turns(self):
        runner = CursorRunner(workdir="/w", model="gpt-4", max_turns=10)
        cmd = runner._build_cmd("prompt", None)
        assert "--model" in cmd
        assert "gpt-4" in cmd
        assert "--max-turns" in cmd
        assert "10" in cmd

    def test_with_session_resume(self):
        runner = CursorRunner(workdir="/w")
        cmd = runner._build_cmd("prompt", "sess_123")
        assert "--resume" in cmd
        assert "sess_123" in cmd

    def test_approve_mcps_when_servers_configured(self):
        runner = CursorRunner(workdir="/w", mcp_servers=[("s", "http://x", {})])
        cmd = runner._build_cmd("prompt", None)
        assert "--approve-mcps" in cmd


# ── CursorRunner.stream error handling ──


class _DummyStream:
    def __init__(self, data: bytes = b""):
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _DummyProc:
    def __init__(self, *, returncode: int | None, stderr: bytes = b""):
        self.returncode = returncode
        self.stdout = _DummyStream()
        self.stderr = _DummyStream(stderr)

    def terminate(self) -> None:
        if self.returncode is None:
            self.returncode = 0

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class TestCursorRunnerStream:
    @pytest.mark.asyncio
    async def test_raises_on_result_error_event(self):
        runner = CursorRunner(workdir="/w")
        proc = _DummyProc(returncode=0)

        async def _fake_lines(_stream):
            yield b'{"type":"result","subtype":"error","error":"boom"}'

        with patch(
            "daiflow.runners.cursor_runner.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ), patch("daiflow.runners.cursor_runner._read_ndjson_lines", _fake_lines):
            with pytest.raises(RuntimeError, match="boom"):
                async for _ in runner.stream("prompt"):
                    pass

    @pytest.mark.asyncio
    async def test_raises_on_nonzero_exit_with_non_json_output(self):
        runner = CursorRunner(workdir="/w")
        proc = _DummyProc(returncode=1, stderr=b"")

        async def _fake_lines(_stream):
            yield b'{"type":"system","subtype":"init","session_id":"sid_1"}'
            yield b"b: Model not available in your region"

        with patch(
            "daiflow.runners.cursor_runner.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ), patch("daiflow.runners.cursor_runner._read_ndjson_lines", _fake_lines):
            with pytest.raises(RuntimeError, match="Model not available"):
                async for _ in runner.stream("prompt"):
                    pass


# ── runner_service integration ──


class TestRunnerServiceCursorIntegration:
    @pytest.mark.asyncio
    async def test_build_cursor_runner_passes_roots_skills_mcp(self, db_session):
        from daiflow.models import McpServer, RunnerConfig

        rc = RunnerConfig(
            id="cur1",
            name="Test Cursor",
            type="cursor",
            config=json.dumps({"api_key": "test-key", "model": "gpt-4", "max_turns": "5"}),
        )
        db_session.add(rc)
        db_session.add(McpServer(id="m1", name="my-tool", url="https://mcp.example.com/mcp", headers='{}', enabled=1))
        await db_session.commit()
        await db_session.refresh(rc)

        from daiflow.services.runner_service import build_runner_from_config

        runner = await build_runner_from_config(
            rc, db_session,
            workdir="/test/workdir",
            allowed_roots=["/test/workdir", "/extra/repo"],
            skill_dir="/test/skills",
        )
        assert isinstance(runner, CursorRunner)
        assert runner._allowed_roots == ["/test/workdir", "/extra/repo"]
        assert runner._skill_dir == "/test/skills"
        assert runner._model == "gpt-4"
        assert runner._max_turns == 5
        my_tool = [s for s in runner._mcp_servers if s[0] == "my-tool"]
        assert len(my_tool) == 1
        assert my_tool[0][1] == "https://mcp.example.com/mcp"


# ── MCP JSON merge tests ──


class TestWriteCursorMcpJsonMerge:
    """Tests for _write_cursor_mcp_json merge behavior.

    _write_cursor_mcp_json should MERGE existing subprocess-format MCPs with
    DaiFlow's HTTP-based MCPs, rather than overwriting.

    Expected behavior:
    - Existing entries in .cursor/mcp.json (subprocess-format) are preserved
    - New DaiFlow HTTP entries are added
    - On name collision, the new DaiFlow entry wins
    """

    def test_preserves_existing_subprocess_mcps(self, tmp_path):
        """Existing subprocess-format MCPs must not be overwritten."""
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir()
        mcp_path = cursor_dir / "mcp.json"
        mcp_path.write_text(json.dumps({
            "mcpServers": {
                "local-tool": {
                    "command": "npx",
                    "args": ["my-mcp-tool"],
                    "env": {"TOKEN": "abc"},
                }
            }
        }))

        _write_cursor_mcp_json(str(tmp_path), [("my-http-mcp", "https://mcp.example.com", {})])

        result = json.loads(mcp_path.read_text())
        # Subprocess entry must survive
        assert "local-tool" in result["mcpServers"]
        assert result["mcpServers"]["local-tool"]["command"] == "npx"
        assert result["mcpServers"]["local-tool"]["args"] == ["my-mcp-tool"]
        # DaiFlow HTTP entry must be added
        assert "my-http-mcp" in result["mcpServers"]
        assert result["mcpServers"]["my-http-mcp"]["url"] == "https://mcp.example.com"

    def test_creates_fresh_when_no_existing(self, tmp_path):
        """If no .cursor/mcp.json exists, creates it with only DaiFlow HTTP servers."""
        _write_cursor_mcp_json(str(tmp_path), [("svc", "https://svc.example.com", {"X-Key": "v"})])

        mcp_path = tmp_path / ".cursor" / "mcp.json"
        assert mcp_path.exists()
        result = json.loads(mcp_path.read_text())
        assert "svc" in result["mcpServers"]
        assert result["mcpServers"]["svc"]["url"] == "https://svc.example.com"
        assert result["mcpServers"]["svc"]["headers"] == {"X-Key": "v"}

    def test_does_nothing_when_no_servers_and_no_existing(self, tmp_path):
        """Empty mcp_servers list with no existing file → file should not be created."""
        _write_cursor_mcp_json(str(tmp_path), [])
        assert not (tmp_path / ".cursor" / "mcp.json").exists()

    def test_preserves_existing_when_no_new_servers(self, tmp_path):
        """Empty new servers list should leave existing file untouched."""
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir()
        mcp_path = cursor_dir / "mcp.json"
        original = {"mcpServers": {"existing": {"command": "old"}}}
        mcp_path.write_text(json.dumps(original))

        _write_cursor_mcp_json(str(tmp_path), [])

        # File should be untouched (or still have the original entry)
        result = json.loads(mcp_path.read_text())
        assert "existing" in result["mcpServers"]

    def test_http_entry_wins_on_name_collision(self, tmp_path):
        """If a name exists in both existing and new servers, new DaiFlow entry wins."""
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir()
        (cursor_dir / "mcp.json").write_text(json.dumps({
            "mcpServers": {
                "svc": {"command": "old-cmd", "args": ["old-arg"]}
            }
        }))

        _write_cursor_mcp_json(str(tmp_path), [("svc", "https://new.example.com", {})])

        result = json.loads((cursor_dir / "mcp.json").read_text())
        assert result["mcpServers"]["svc"]["url"] == "https://new.example.com"
        assert "command" not in result["mcpServers"]["svc"]

    def test_multiple_http_servers_all_added(self, tmp_path):
        """Multiple DaiFlow HTTP servers should all appear in the output."""
        _write_cursor_mcp_json(str(tmp_path), [
            ("svc-a", "https://a.example.com", {}),
            ("svc-b", "https://b.example.com", {"X-Token": "tok"}),
        ])

        result = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        assert "svc-a" in result["mcpServers"]
        assert "svc-b" in result["mcpServers"]
        assert result["mcpServers"]["svc-b"]["headers"] == {"X-Token": "tok"}

    def test_invalid_json_in_existing_file_replaced(self, tmp_path):
        """If the existing .cursor/mcp.json is invalid JSON, should not crash — creates fresh."""
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir()
        (cursor_dir / "mcp.json").write_text("{ invalid json content !!!")

        # Should not raise
        _write_cursor_mcp_json(str(tmp_path), [("fresh", "https://fresh.example.com", {})])

        result = json.loads((cursor_dir / "mcp.json").read_text())
        assert "fresh" in result["mcpServers"]


# ── Connection test ──


class TestCursorConnectionTest:
    @pytest.mark.asyncio
    async def test_agent_version_check(self, client):
        """Test that the cursor runner connection test calls `agent --version`."""
        resp = await client.post("/api/settings/runners", json={
            "name": "Test Cursor",
            "type": "cursor",
            "config": {},
        })
        if resp.status_code != 200:
            pytest.skip("Runner config API not available")

        runner_id = resp.json().get("id")
        if not runner_id:
            pytest.skip("No runner ID returned")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = await client.post(f"/api/settings/runners/{runner_id}/test")
            assert result.status_code == 200
            assert result.json()["ok"] is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == ["agent", "--version"]
