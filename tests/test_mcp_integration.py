"""Tests for MCP server integration with Cody client builder."""

from unittest.mock import MagicMock, patch

from daiflow.models import McpServer, Setting


class TestMcpCodyIntegration:
    """Verify build_cody_client injects MCP servers into the Cody builder."""

    async def test_mcp_servers_injected(self, db_session):
        """Enabled MCP servers should be added via mcp_http_server()."""
        # Seed settings
        db_session.add(Setting(key="cody_model", value="test-model"))
        db_session.add(Setting(key="cody_base_url", value="https://api.test.com"))
        db_session.add(Setting(key="cody_api_key", value="sk-test"))
        # Seed MCP servers
        db_session.add(McpServer(id="s1", name="feishu", url="https://mcp.feishu.cn/mcp", headers='{"X-Token": "abc"}', enabled=1))
        db_session.add(McpServer(id="s2", name="github", url="https://mcp.github.com", headers="{}", enabled=1))
        db_session.add(McpServer(id="s3", name="disabled", url="https://disabled.com", headers="{}", enabled=0))
        await db_session.commit()

        mock_builder = MagicMock()
        mock_builder.workdir.return_value = mock_builder
        mock_builder.model.return_value = mock_builder
        mock_builder.base_url.return_value = mock_builder
        mock_builder.api_key.return_value = mock_builder
        mock_builder.db_path.return_value = mock_builder
        mock_builder.allowed_roots.return_value = mock_builder
        mock_builder.strict_read_boundary.return_value = mock_builder
        mock_builder.mcp_http_server.return_value = mock_builder
        mock_builder.auto_start_mcp.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()

        mock_cody_cls = MagicMock(return_value=mock_builder)

        with patch("daiflow.services.cody_service.Cody", mock_cody_cls, create=True):
            # Patch the import inside the function
            with patch.dict("sys.modules", {"cody": MagicMock(Cody=mock_cody_cls)}):
                from daiflow.services.cody_service import build_cody_client
                await build_cody_client(db_session, "/tmp/workdir")

        # Should have called mcp_http_server for the 2 enabled servers
        calls = mock_builder.mcp_http_server.call_args_list
        assert len(calls) == 2
        # Check first server
        assert calls[0][0][0] == "feishu"
        assert calls[0][1]["url"] == "https://mcp.feishu.cn/mcp"
        assert calls[0][1]["headers"] == {"X-Token": "abc"}
        # Check second server
        assert calls[1][0][0] == "github"
        assert calls[1][1]["url"] == "https://mcp.github.com"
        assert calls[1][1]["headers"] == {}
        # auto_start_mcp should be called once
        mock_builder.auto_start_mcp.assert_called_once_with(True)

    async def test_no_mcp_servers_no_auto_start(self, db_session):
        """When no MCP servers exist, auto_start_mcp should not be called."""
        db_session.add(Setting(key="cody_model", value="test-model"))
        db_session.add(Setting(key="cody_base_url", value="https://api.test.com"))
        db_session.add(Setting(key="cody_api_key", value="sk-test"))
        await db_session.commit()

        mock_builder = MagicMock()
        mock_builder.workdir.return_value = mock_builder
        mock_builder.model.return_value = mock_builder
        mock_builder.base_url.return_value = mock_builder
        mock_builder.api_key.return_value = mock_builder
        mock_builder.db_path.return_value = mock_builder
        mock_builder.allowed_roots.return_value = mock_builder
        mock_builder.strict_read_boundary.return_value = mock_builder
        mock_builder.mcp_http_server.return_value = mock_builder
        mock_builder.auto_start_mcp.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()

        mock_cody_cls = MagicMock(return_value=mock_builder)

        with patch.dict("sys.modules", {"cody": MagicMock(Cody=mock_cody_cls)}):
            from daiflow.services.cody_service import build_cody_client
            await build_cody_client(db_session, "/tmp/workdir")

        mock_builder.mcp_http_server.assert_not_called()
        mock_builder.auto_start_mcp.assert_not_called()

    async def test_disabled_servers_skipped(self, db_session):
        """Disabled MCP servers should not be injected."""
        db_session.add(Setting(key="cody_model", value="test-model"))
        db_session.add(Setting(key="cody_base_url", value="https://api.test.com"))
        db_session.add(Setting(key="cody_api_key", value="sk-test"))
        db_session.add(McpServer(id="s1", name="off", url="https://off.com", headers="{}", enabled=0))
        await db_session.commit()

        mock_builder = MagicMock()
        mock_builder.workdir.return_value = mock_builder
        mock_builder.model.return_value = mock_builder
        mock_builder.base_url.return_value = mock_builder
        mock_builder.api_key.return_value = mock_builder
        mock_builder.db_path.return_value = mock_builder
        mock_builder.allowed_roots.return_value = mock_builder
        mock_builder.strict_read_boundary.return_value = mock_builder
        mock_builder.mcp_http_server.return_value = mock_builder
        mock_builder.auto_start_mcp.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()

        mock_cody_cls = MagicMock(return_value=mock_builder)

        with patch.dict("sys.modules", {"cody": MagicMock(Cody=mock_cody_cls)}):
            from daiflow.services.cody_service import build_cody_client
            await build_cody_client(db_session, "/tmp/workdir")

        mock_builder.mcp_http_server.assert_not_called()
        mock_builder.auto_start_mcp.assert_not_called()
