"""Tests for the built-in dev preview proxy route."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest


class TestDevPreviewProxy:

    async def test_proxy_not_running(self, client):
        """Returns 404 when dev server is not running for the task."""
        with patch("daiflow.routers.preview_proxy.dev_server_manager") as mock_mgr:
            mock_mgr.status.return_value = {"running": False, "url": "", "port": 0, "preview_url": ""}
            resp = await client.get("/api/dev-preview/task123/some/path")
        assert resp.status_code == 404
        assert "not running" in resp.text

    async def test_proxy_success(self, client):
        """Proxies to the correct port when dev server is running."""
        with patch("daiflow.routers.preview_proxy.dev_server_manager") as mock_mgr, \
             patch("daiflow.routers.preview_proxy._get_client") as mock_get_client:
            mock_mgr.status.return_value = {"running": True, "url": "http://localhost:5173", "port": 5173, "preview_url": ""}

            mock_response = httpx.Response(
                status_code=200,
                content=b"<html><body>Hello</body></html>",
                headers={"content-type": "text/html"},
            )
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            resp = await client.get("/api/dev-preview/task123/index.html")

        assert resp.status_code == 200
        mock_client.request.assert_called_once()
        call_kwargs = mock_client.request.call_args
        assert "http://127.0.0.1:5173/index.html" in call_kwargs.kwargs.get("url", call_kwargs.args[1] if len(call_kwargs.args) > 1 else "")

    async def test_proxy_strips_security_headers(self, client):
        """Strips X-Frame-Options and CSP headers from upstream response."""
        with patch("daiflow.routers.preview_proxy.dev_server_manager") as mock_mgr, \
             patch("daiflow.routers.preview_proxy._get_client") as mock_get_client:
            mock_mgr.status.return_value = {"running": True, "url": "http://localhost:5173", "port": 5173, "preview_url": ""}

            mock_response = httpx.Response(
                status_code=200,
                content=b"<html></html>",
                headers={
                    "content-type": "text/html",
                    "x-frame-options": "DENY",
                    "content-security-policy": "frame-ancestors 'none'",
                    "x-custom": "keep-this",
                },
            )
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            resp = await client.get("/api/dev-preview/task123/")

        assert resp.status_code == 200
        assert "x-frame-options" not in resp.headers
        assert "content-security-policy" not in resp.headers
        assert resp.headers.get("x-custom") == "keep-this"

    async def test_proxy_passes_query_params(self, client):
        """Query parameters are forwarded to the upstream."""
        with patch("daiflow.routers.preview_proxy.dev_server_manager") as mock_mgr, \
             patch("daiflow.routers.preview_proxy._get_client") as mock_get_client:
            mock_mgr.status.return_value = {"running": True, "url": "http://localhost:5173", "port": 5173, "preview_url": ""}

            mock_response = httpx.Response(status_code=200, content=b"ok")
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            resp = await client.get("/api/dev-preview/task123/api/data?page=1&size=10")

        assert resp.status_code == 200
        call_url = mock_client.request.call_args.kwargs.get("url", "")
        assert "page=1" in call_url
        assert "size=10" in call_url

    async def test_proxy_upstream_error(self, client):
        """Returns 502 when upstream request fails."""
        with patch("daiflow.routers.preview_proxy.dev_server_manager") as mock_mgr, \
             patch("daiflow.routers.preview_proxy._get_client") as mock_get_client:
            mock_mgr.status.return_value = {"running": True, "url": "http://localhost:5173", "port": 5173, "preview_url": ""}

            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get_client.return_value = mock_client

            resp = await client.get("/api/dev-preview/task123/")

        assert resp.status_code == 502


class TestLegacyUrlProxy:

    async def test_missing_url_param(self, client):
        resp = await client.get("/api/preview-proxy")
        assert resp.status_code == 400

    async def test_invalid_scheme(self, client):
        resp = await client.get("/api/preview-proxy?url=ftp://evil.com")
        assert resp.status_code == 400

    async def test_success(self, client):
        with patch("daiflow.routers.preview_proxy._get_client") as mock_get_client:
            mock_response = httpx.Response(
                status_code=200,
                content=b"<html>hello</html>",
                headers={"content-type": "text/html"},
            )
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            resp = await client.get("/api/preview-proxy?url=https://example.com/page")

        assert resp.status_code == 200
