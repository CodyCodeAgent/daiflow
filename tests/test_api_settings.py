"""Tests for settings API endpoints."""

import pytest


class TestSettingsAPI:
    async def test_get_settings_empty(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        assert resp.json() == {}

    async def test_put_settings(self, client):
        resp = await client.put("/api/settings", json={
            "cody_model": "claude-opus-4-6",
            "cody_base_url": "https://api.anthropic.com",
            "cody_api_key": "sk-ant-12345678901234567890",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_get_settings_masks_api_key(self, client):
        await client.put("/api/settings", json={
            "cody_api_key": "sk-ant-12345678901234567890",
        })
        resp = await client.get("/api/settings")
        data = resp.json()
        key = data["cody_api_key"]
        # Key should be masked: first 4 + *** + last 4
        assert key.startswith("sk-a")
        assert key.endswith("7890")
        assert "****" in key or "*" in key

    async def test_get_settings_masks_short_api_key(self, client):
        await client.put("/api/settings", json={"cody_api_key": "short"})
        resp = await client.get("/api/settings")
        assert resp.json()["cody_api_key"] == "****"

    async def test_update_theme(self, client):
        resp = await client.put("/api/settings", json={"theme": "light"})
        assert resp.status_code == 200
        resp = await client.get("/api/settings")
        assert resp.json()["theme"] == "light"

    async def test_update_overwrites(self, client):
        await client.put("/api/settings", json={"cody_model": "model-a"})
        await client.put("/api/settings", json={"cody_model": "model-b"})
        resp = await client.get("/api/settings")
        assert resp.json()["cody_model"] == "model-b"

    async def test_check_not_configured(self, client):
        resp = await client.get("/api/settings/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["model"] == ""

    async def test_check_configured(self, client):
        await client.put("/api/settings", json={
            "cody_model": "claude-opus-4-6",
            "cody_base_url": "https://api.anthropic.com",
            "cody_api_key": "sk-ant-12345678901234567890",
        })
        resp = await client.get("/api/settings/check")
        data = resp.json()
        assert data["configured"] is True
        assert data["model"] == "claude-opus-4-6"

    async def test_check_partial_config(self, client):
        await client.put("/api/settings", json={
            "cody_model": "claude-opus-4-6",
            # Missing base_url and api_key
        })
        resp = await client.get("/api/settings/check")
        assert resp.json()["configured"] is False

    async def test_empty_string_value_rejected(self, client):
        await client.put("/api/settings", json={"cody_model": "model-a"})
        # Sending empty string should return 400 for required AI fields
        resp = await client.put("/api/settings", json={"cody_model": "   "})
        assert resp.status_code == 400
        # Original value should be preserved
        resp = await client.get("/api/settings")
        assert resp.json()["cody_model"] == "model-a"

    async def test_empty_base_url_rejected(self, client):
        resp = await client.put("/api/settings", json={"cody_base_url": ""})
        assert resp.status_code == 400
        assert "cody_base_url" in resp.json()["detail"]

    async def test_empty_api_key_rejected(self, client):
        resp = await client.put("/api/settings", json={"cody_api_key": "  "})
        assert resp.status_code == 400
        assert "cody_api_key" in resp.json()["detail"]

    async def test_empty_theme_allowed(self, client):
        """Theme and language are optional fields — empty values should be accepted."""
        resp = await client.put("/api/settings", json={"theme": ""})
        assert resp.status_code == 200

    async def test_masked_api_key_not_overwritten(self, client):
        """Sending back a masked API key should not overwrite the real key."""
        real_key = "sk-ant-12345678901234567890"
        await client.put("/api/settings", json={
            "cody_model": "claude-opus-4-6",
            "cody_base_url": "https://api.anthropic.com",
            "cody_api_key": real_key,
        })
        # Get the masked value
        resp = await client.get("/api/settings")
        masked_key = resp.json()["cody_api_key"]
        assert "****" in masked_key
        # Send the masked value back — should not overwrite
        await client.put("/api/settings", json={"cody_api_key": masked_key})
        # Verify the real key is preserved (check still passes)
        resp = await client.get("/api/settings/check")
        assert resp.json()["configured"] is True


class TestMcpServersAPI:
    """Tests for MCP server CRUD endpoints."""

    async def test_list_empty(self, client):
        resp = await client.get("/api/settings/mcp-servers")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_server(self, client):
        resp = await client.post("/api/settings/mcp-servers", json={
            "name": "feishu",
            "url": "https://mcp.feishu.cn/mcp",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "feishu"
        assert data["url"] == "https://mcp.feishu.cn/mcp"
        assert data["headers"] == {}
        assert data["enabled"] is True
        assert "id" in data

    async def test_create_with_headers(self, client):
        resp = await client.post("/api/settings/mcp-servers", json={
            "name": "github",
            "url": "https://mcp.github.com",
            "headers": {"Authorization": "Bearer token123"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["headers"] == {"Authorization": "Bearer token123"}

    async def test_create_disabled(self, client):
        resp = await client.post("/api/settings/mcp-servers", json={
            "name": "disabled-srv",
            "url": "https://example.com/mcp",
            "enabled": False,
        })
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_create_duplicate_name_rejected(self, client):
        await client.post("/api/settings/mcp-servers", json={
            "name": "feishu", "url": "https://mcp.feishu.cn/mcp",
        })
        resp = await client.post("/api/settings/mcp-servers", json={
            "name": "feishu", "url": "https://other.url/mcp",
        })
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    async def test_create_empty_name_rejected(self, client):
        resp = await client.post("/api/settings/mcp-servers", json={
            "name": "  ", "url": "https://example.com/mcp",
        })
        assert resp.status_code == 422  # Pydantic validation error

    async def test_create_empty_url_rejected(self, client):
        resp = await client.post("/api/settings/mcp-servers", json={
            "name": "test", "url": "",
        })
        assert resp.status_code == 422

    async def test_list_returns_created_servers(self, client):
        await client.post("/api/settings/mcp-servers", json={
            "name": "srv-a", "url": "https://a.com/mcp",
        })
        await client.post("/api/settings/mcp-servers", json={
            "name": "srv-b", "url": "https://b.com/mcp",
        })
        resp = await client.get("/api/settings/mcp-servers")
        assert resp.status_code == 200
        servers = resp.json()
        assert len(servers) == 2
        names = {s["name"] for s in servers}
        assert names == {"srv-a", "srv-b"}

    async def test_update_server(self, client):
        create_resp = await client.post("/api/settings/mcp-servers", json={
            "name": "old-name", "url": "https://old.com/mcp",
        })
        server_id = create_resp.json()["id"]

        resp = await client.put(f"/api/settings/mcp-servers/{server_id}", json={
            "name": "new-name",
            "url": "https://new.com/mcp",
            "headers": {"X-Token": "abc"},
            "enabled": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "new-name"
        assert data["url"] == "https://new.com/mcp"
        assert data["headers"] == {"X-Token": "abc"}
        assert data["enabled"] is False

    async def test_update_partial(self, client):
        """Updating only one field should preserve others."""
        create_resp = await client.post("/api/settings/mcp-servers", json={
            "name": "srv", "url": "https://orig.com/mcp",
            "headers": {"Key": "val"},
        })
        server_id = create_resp.json()["id"]

        resp = await client.put(f"/api/settings/mcp-servers/{server_id}", json={
            "url": "https://updated.com/mcp",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "srv"  # unchanged
        assert data["url"] == "https://updated.com/mcp"  # updated
        assert data["headers"] == {"Key": "val"}  # unchanged

    async def test_update_duplicate_name_rejected(self, client):
        await client.post("/api/settings/mcp-servers", json={
            "name": "taken", "url": "https://a.com/mcp",
        })
        create_resp = await client.post("/api/settings/mcp-servers", json={
            "name": "other", "url": "https://b.com/mcp",
        })
        server_id = create_resp.json()["id"]

        resp = await client.put(f"/api/settings/mcp-servers/{server_id}", json={
            "name": "taken",
        })
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    async def test_update_same_name_allowed(self, client):
        """Renaming to the same name (no change) should not fail."""
        create_resp = await client.post("/api/settings/mcp-servers", json={
            "name": "keep-name", "url": "https://a.com/mcp",
        })
        server_id = create_resp.json()["id"]

        resp = await client.put(f"/api/settings/mcp-servers/{server_id}", json={
            "name": "keep-name",
        })
        assert resp.status_code == 200

    async def test_update_nonexistent_returns_404(self, client):
        resp = await client.put("/api/settings/mcp-servers/nonexistent", json={
            "name": "x",
        })
        assert resp.status_code == 404

    async def test_update_empty_name_rejected(self, client):
        create_resp = await client.post("/api/settings/mcp-servers", json={
            "name": "srv", "url": "https://a.com/mcp",
        })
        server_id = create_resp.json()["id"]
        resp = await client.put(f"/api/settings/mcp-servers/{server_id}", json={
            "name": "",
        })
        assert resp.status_code == 422

    async def test_delete_server(self, client):
        create_resp = await client.post("/api/settings/mcp-servers", json={
            "name": "to-delete", "url": "https://del.com/mcp",
        })
        server_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/settings/mcp-servers/{server_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify it's gone
        resp = await client.get("/api/settings/mcp-servers")
        assert all(s["id"] != server_id for s in resp.json())

    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/settings/mcp-servers/nonexistent")
        assert resp.status_code == 404
