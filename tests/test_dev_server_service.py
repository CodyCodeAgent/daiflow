"""Unit tests for DevServerManager and build_preview_url."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from daiflow.services.dev_server_service import DevServerManager, build_preview_url


def _make_mock_proc(running=True):
    proc = MagicMock()
    proc.returncode = None if running else 0
    proc.pid = 12345
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


_SVC = "daiflow.services.dev_server_service"
_CFG = "daiflow.config"


class TestBuildPreviewUrl:

    def test_local_mode_no_preview_url(self):
        with              patch(f"{_CFG}.PREVIEW_MODE", "local"):
            url = build_preview_url("task1", 5173, "")
        assert url == "http://localhost:5173"

    def test_local_mode_with_preview_url(self):
        with patch(f"{_CFG}.PREVIEW_MODE", "local"):
            url = build_preview_url("task1", 5173, "https://example.com/app/page")
        assert url == "https://example.com/app/page"

    def test_builtin_mode_no_preview_url(self):
        with patch(f"{_CFG}.PREVIEW_MODE", "builtin"):
            url = build_preview_url("task1", 5173, "", server_host="myserver:8000")
        assert url == "http://myserver:8000/api/dev-preview/task1/"

    def test_builtin_mode_with_preview_url_path(self):
        with patch(f"{_CFG}.PREVIEW_MODE", "builtin"):
            url = build_preview_url(
                "task1", 5173, "https://example.com/cost/accrual",
                server_host="devbox.company.com:8000",
            )
        assert url == "http://devbox.company.com:8000/api/dev-preview/task1/cost/accrual"

    def test_builtin_mode_default_host(self):
        with patch(f"{_CFG}.PREVIEW_MODE", "builtin"):
            url = build_preview_url("task1", 5173, "")
        assert url == "http://localhost:8000/api/dev-preview/task1/"

    def test_builtin_mode_https_on_443(self):
        with patch(f"{_CFG}.PREVIEW_MODE", "builtin"):
            url = build_preview_url("task1", 5173, "", server_host="daiflow.example.com:443")
        assert url == "https://daiflow.example.com:443/api/dev-preview/task1/"


class TestDevServerManager:

    async def test_start_success_local_mode(self):
        manager = DevServerManager()
        mock_proc = _make_mock_proc()
        with patch(f"{_SVC}.asyncio.create_subprocess_shell", return_value=mock_proc), \
             patch(f"{_SVC}._is_port_in_use", return_value=False), \
             patch(f"{_SVC}._wait_for_port", new_callable=AsyncMock), \
             patch(f"{_CFG}.PREVIEW_MODE", "local"):
            result = await manager.start("task1", "repo1", "npm run dev", 5173, "/tmp")

        assert result["running"] is True
        assert result["url"] == "http://localhost:5173"
        assert result["port"] == 5173
        assert result["preview_url"] == ""
        assert "task1" in manager._processes

    async def test_start_success_builtin_mode(self):
        manager = DevServerManager()
        mock_proc = _make_mock_proc()
        with patch(f"{_SVC}.asyncio.create_subprocess_shell", return_value=mock_proc), \
             patch(f"{_SVC}._is_port_in_use", return_value=False), \
             patch(f"{_SVC}._wait_for_port", new_callable=AsyncMock), \
             patch(f"{_CFG}.PREVIEW_MODE", "builtin"):
            result = await manager.start(
                "task1", "repo1", "npm run dev", 5173, "/tmp",
                server_host="devbox:8000",
            )

        assert result["running"] is True
        assert result["url"] == "http://devbox:8000/api/dev-preview/task1/"
        assert result["port"] == 5173

    async def test_start_returns_existing_when_already_running(self):
        manager = DevServerManager()
        mock_proc = _make_mock_proc()
        with patch(f"{_SVC}.asyncio.create_subprocess_shell", return_value=mock_proc) as mock_create, \
             patch(f"{_SVC}._is_port_in_use", return_value=False), \
             patch(f"{_SVC}._wait_for_port", new_callable=AsyncMock), \
             patch(f"{_CFG}.PREVIEW_MODE", "local"):
            await manager.start("task1", "repo1", "npm run dev", 5173, "/tmp")
            result = await manager.start("task1", "repo1", "npm run dev", 5173, "/tmp")

        assert result["running"] is True
        assert mock_create.call_count == 1

    async def test_start_raises_when_port_in_use(self):
        manager = DevServerManager()
        with patch(f"{_SVC}._is_port_in_use", return_value=True):
            with pytest.raises(RuntimeError, match="already in use"):
                await manager.start("task1", "repo1", "npm run dev", 5173, "/tmp")

    async def test_start_raises_on_timeout(self):
        manager = DevServerManager()
        mock_proc = _make_mock_proc()
        with patch(f"{_SVC}.asyncio.create_subprocess_shell", return_value=mock_proc), \
             patch(f"{_SVC}._is_port_in_use", return_value=False), \
             patch(f"{_SVC}._wait_for_port", new_callable=AsyncMock, side_effect=TimeoutError):
            with pytest.raises(RuntimeError, match="did not become ready"):
                await manager.start("task1", "repo1", "npm run dev", 5173, "/tmp")
        assert "task1" not in manager._processes

    async def test_stop_terminates_process(self):
        manager = DevServerManager()
        mock_proc = _make_mock_proc()
        with patch(f"{_SVC}.asyncio.create_subprocess_shell", return_value=mock_proc), \
             patch(f"{_SVC}._is_port_in_use", return_value=False), \
             patch(f"{_SVC}._wait_for_port", new_callable=AsyncMock), \
             patch(f"{_CFG}.PREVIEW_MODE", "local"):
            await manager.start("task1", "repo1", "npm run dev", 5173, "/tmp")
        await manager.stop("task1")
        mock_proc.terminate.assert_called_once()
        assert "task1" not in manager._processes

    async def test_stop_noop_when_no_process(self):
        manager = DevServerManager()
        await manager.stop("nonexistent")

    async def test_status_running(self):
        manager = DevServerManager()
        mock_proc = _make_mock_proc()
        with patch(f"{_SVC}.asyncio.create_subprocess_shell", return_value=mock_proc), \
             patch(f"{_SVC}._is_port_in_use", return_value=False), \
             patch(f"{_SVC}._wait_for_port", new_callable=AsyncMock), \
             patch(f"{_CFG}.PREVIEW_MODE", "local"):
            await manager.start("task1", "repo1", "npm run dev", 5173, "/tmp")

        with patch(f"{_CFG}.PREVIEW_MODE", "local"):
            result = manager.status("task1")
        assert result["running"] is True
        assert result["url"] == "http://localhost:5173"

    async def test_status_not_running(self):
        manager = DevServerManager()
        result = manager.status("nonexistent")
        assert result == {"running": False, "url": "", "port": 0, "preview_url": ""}

    async def test_stop_all(self):
        manager = DevServerManager()
        mock_proc1 = _make_mock_proc()
        mock_proc2 = _make_mock_proc()
        with patch(f"{_SVC}.asyncio.create_subprocess_shell") as mock_create, \
             patch(f"{_SVC}._is_port_in_use", return_value=False), \
             patch(f"{_SVC}._wait_for_port", new_callable=AsyncMock), \
             patch(f"{_CFG}.PREVIEW_MODE", "local"):
            mock_create.return_value = mock_proc1
            await manager.start("task1", "repo1", "cmd1", 5173, "/tmp")
            mock_create.return_value = mock_proc2
            await manager.start("task2", "repo2", "cmd2", 5174, "/tmp")

        assert len(manager._processes) == 2
        await manager.stop_all()
        assert len(manager._processes) == 0
