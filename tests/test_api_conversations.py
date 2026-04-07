"""Tests for conversations API endpoints."""

from unittest.mock import AsyncMock, patch

from daiflow.models import Conversation, ConversationStatus, Project, Session, SessionStatus


async def _create_project(client):
    resp = await client.post("/api/projects", json={"name": "TestProj"})
    return resp.json()["id"]


# Mock init_conversation since it runs background code copy + skill sync
_mock_init = patch("daiflow.routers.conversations.init_conversation", new_callable=AsyncMock)


class TestConversationsCRUD:
    @_mock_init
    async def test_list_empty(self, mock_init, client):
        resp = await client.get("/api/conversations")
        assert resp.status_code == 200
        assert resp.json() == []

    @_mock_init
    async def test_create_conversation(self, mock_init, client):
        pid = await _create_project(client)
        resp = await client.post("/api/conversations", json={
            "name": "Chat about API",
            "project_id": pid,
            "description": "Discuss refactoring",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Chat about API"
        assert data["project_id"] == pid
        assert data["description"] == "Discuss refactoring"
        assert data["status"] == ConversationStatus.CREATING
        assert data["id"]
        assert data["created_at"]
        mock_init.assert_called_once()

    @_mock_init
    async def test_create_conversation_minimal(self, mock_init, client):
        pid = await _create_project(client)
        resp = await client.post("/api/conversations", json={
            "name": "Quick chat",
            "project_id": pid,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Quick chat"
        assert data["description"] == ""
        assert data["runner_id"] is None

    @_mock_init
    async def test_get_conversation(self, mock_init, client):
        pid = await _create_project(client)
        create_resp = await client.post("/api/conversations", json={
            "name": "Test Conv", "project_id": pid,
        })
        cid = create_resp.json()["id"]
        resp = await client.get(f"/api/conversations/{cid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Conv"

    async def test_get_conversation_not_found(self, client):
        resp = await client.get("/api/conversations/nonexistent")
        assert resp.status_code == 404

    @_mock_init
    async def test_list_conversations_filter_by_project(self, mock_init, client):
        pid1 = await _create_project(client)
        pid2 = (await client.post("/api/projects", json={"name": "Proj2"})).json()["id"]

        await client.post("/api/conversations", json={"name": "Conv1", "project_id": pid1})
        await client.post("/api/conversations", json={"name": "Conv2", "project_id": pid2})
        await client.post("/api/conversations", json={"name": "Conv3", "project_id": pid1})

        all_resp = await client.get("/api/conversations")
        assert len(all_resp.json()) == 3

        filtered = await client.get(f"/api/conversations?project_id={pid1}")
        names = [c["name"] for c in filtered.json()]
        assert len(names) == 2
        assert "Conv2" not in names

    @_mock_init
    async def test_delete_conversation(self, mock_init, client):
        pid = await _create_project(client)
        create_resp = await client.post("/api/conversations", json={
            "name": "To Delete", "project_id": pid,
        })
        cid = create_resp.json()["id"]

        resp = await client.delete(f"/api/conversations/{cid}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify it's gone
        resp = await client.get(f"/api/conversations/{cid}")
        assert resp.status_code == 404

    async def test_delete_conversation_not_found(self, client):
        resp = await client.delete("/api/conversations/nonexistent")
        assert resp.status_code == 404

    @_mock_init
    async def test_conversations_deleted_with_project(self, mock_init, client):
        """Conversations cascade-delete when project is deleted."""
        pid = await _create_project(client)
        await client.post("/api/conversations", json={"name": "Conv", "project_id": pid})

        # Delete project
        await client.delete(f"/api/projects/{pid}")

        # Conversations should be gone
        resp = await client.get("/api/conversations")
        assert resp.json() == []


class TestConversationInit:
    @_mock_init
    async def test_init_sessions_empty_before_init(self, mock_init, client):
        pid = await _create_project(client)
        create_resp = await client.post("/api/conversations", json={
            "name": "Conv", "project_id": pid,
        })
        cid = create_resp.json()["id"]

        resp = await client.get(f"/api/conversations/{cid}/init/sessions")
        assert resp.status_code == 200
        # No sessions created yet (mock prevents init from running)
        assert resp.json() == []

    @_mock_init
    async def test_retry_init_on_failed(self, mock_init, client, db_session):
        pid = await _create_project(client)
        create_resp = await client.post("/api/conversations", json={
            "name": "Conv", "project_id": pid,
        })
        cid = create_resp.json()["id"]

        # Manually mark as FAILED
        conv = await db_session.get(Conversation, cid)
        conv.status = ConversationStatus.FAILED
        await db_session.commit()

        resp = await client.post(f"/api/conversations/{cid}/retry-init")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert mock_init.call_count == 2  # initial create + retry

    @_mock_init
    async def test_retry_init_on_ready_rejected(self, mock_init, client, db_session):
        pid = await _create_project(client)
        create_resp = await client.post("/api/conversations", json={
            "name": "Conv", "project_id": pid,
        })
        cid = create_resp.json()["id"]

        # Mark as READY
        conv = await db_session.get(Conversation, cid)
        conv.status = ConversationStatus.READY
        await db_session.commit()

        resp = await client.post(f"/api/conversations/{cid}/retry-init")
        assert resp.status_code == 200
        assert resp.json()["ok"] is False


class TestConversationSchema:
    @_mock_init
    async def test_response_fields(self, mock_init, client):
        pid = await _create_project(client)
        resp = await client.post("/api/conversations", json={
            "name": "Schema Test",
            "project_id": pid,
            "description": "desc",
        })
        data = resp.json()
        # Verify all expected fields are present
        assert set(data.keys()) == {
            "id", "name", "project_id", "description", "status",
            "runner_id", "created_at", "updated_at",
        }
        # Verify datetime serialization
        assert data["created_at"].endswith("Z")

    async def test_create_missing_name(self, client):
        pid = await _create_project(client)
        resp = await client.post("/api/conversations", json={
            "project_id": pid,
        })
        assert resp.status_code == 422

    async def test_create_missing_project_id(self, client):
        resp = await client.post("/api/conversations", json={
            "name": "No project",
        })
        assert resp.status_code == 422

    async def test_create_invalid_project_id(self, client):
        resp = await client.post("/api/conversations", json={
            "name": "Bad project",
            "project_id": "nonexistent",
        })
        assert resp.status_code == 404

    async def test_create_empty_name(self, client):
        pid = await _create_project(client)
        resp = await client.post("/api/conversations", json={
            "name": "  ",
            "project_id": pid,
        })
        assert resp.status_code == 422

    @_mock_init
    async def test_create_name_trimmed(self, mock_init, client):
        pid = await _create_project(client)
        resp = await client.post("/api/conversations", json={
            "name": "  spaces  ",
            "project_id": pid,
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "spaces"
