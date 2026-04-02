"""Integration tests for Dev Server API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest


_mock_init = patch("daiflow.routers.tasks.init_task", new_callable=AsyncMock)


async def _create_project_with_dev_repo(client) -> tuple[str, str]:
    """Create a project with a frontend repo that has dev server config, plus a task."""
    resp = await client.post("/api/projects", json={
        "name": "TestProj",
        "repos": [{
            "local_path": "/tmp/test-repo",
            "repo_type": "frontend",
            "dev_command": "npm run dev",
            "dev_port": 5173,
        }],
    })
    pid = resp.json()["id"]
    resp = await client.post("/api/tasks", json={"name": "T", "project_id": pid})
    tid = resp.json()["id"]
    return pid, tid


async def _create_project_without_dev_repo(client) -> tuple[str, str]:
    """Create a project with a repo that has NO dev server config."""
    resp = await client.post("/api/projects", json={
        "name": "NoDevProj",
        "repos": [{
            "local_path": "/tmp/backend-repo",
            "repo_type": "backend",
        }],
    })
    pid = resp.json()["id"]
    resp = await client.post("/api/tasks", json={"name": "T", "project_id": pid})
    tid = resp.json()["id"]
    return pid, tid


class TestDevServerAPI:

    @_mock_init
    async def test_start_task_not_found(self, mock_init, client):
        resp = await client.post("/api/tasks/nonexistent/dev-server/start")
        assert resp.status_code == 404

    @_mock_init
    async def test_start_no_dev_repo(self, mock_init, client):
        _, tid = await _create_project_without_dev_repo(client)
        resp = await client.post(f"/api/tasks/{tid}/dev-server/start")
        assert resp.status_code == 400
        assert "No repo with dev server configured" in resp.json()["detail"]

    @_mock_init
    async def test_start_resolve_path_none(self, mock_init, client):
        """Repo has dev config but resolve_repo_path returns None."""
        resp = await client.post("/api/projects", json={
            "name": "GitProj",
            "repos": [{
                "git_url": "https://github.com/test/repo",
                "repo_type": "frontend",
                "dev_command": "npm run dev",
                "dev_port": 5173,
            }],
        })
        pid = resp.json()["id"]
        resp = await client.post("/api/tasks", json={"name": "T", "project_id": pid})
        tid = resp.json()["id"]

        with patch("daiflow.services.task_service.resolve_repo_path", return_value=None):
            resp = await client.post(f"/api/tasks/{tid}/dev-server/start")
        assert resp.status_code == 400
        assert "Cannot resolve repo path" in resp.json()["detail"]

    @_mock_init
    async def test_start_runtime_error(self, mock_init, client):
        _, tid = await _create_project_with_dev_repo(client)
        with patch("daiflow.routers.tasks.dev_server_manager") as mock_mgr:
            mock_mgr.start = AsyncMock(side_effect=RuntimeError("Port 5173 is already in use"))
            resp = await client.post(f"/api/tasks/{tid}/dev-server/start")
        assert resp.status_code == 400
        assert "Port 5173" in resp.json()["detail"]

    @_mock_init
    async def test_start_success(self, mock_init, client):
        _, tid = await _create_project_with_dev_repo(client)
        with patch("daiflow.routers.tasks.dev_server_manager") as mock_mgr:
            mock_mgr.start = AsyncMock(return_value={
                "running": True, "url": "http://localhost:5173", "port": 5173,
            })
            resp = await client.post(f"/api/tasks/{tid}/dev-server/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["url"] == "http://localhost:5173"
        assert data["port"] == 5173

    @_mock_init
    async def test_stop(self, mock_init, client):
        with patch("daiflow.routers.tasks.dev_server_manager") as mock_mgr:
            mock_mgr.stop = AsyncMock()
            resp = await client.post("/api/tasks/any-task-id/dev-server/stop")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @_mock_init
    async def test_status_not_running(self, mock_init, client):
        with patch("daiflow.routers.tasks.dev_server_manager") as mock_mgr:
            mock_mgr.status.return_value = {"running": False, "url": "", "port": 0}
            resp = await client.get("/api/tasks/any-task-id/dev-server/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
