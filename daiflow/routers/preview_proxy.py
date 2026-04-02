"""Built-in reverse proxy for dev preview.

Two modes:
- /api/dev-preview/{task_id}/{path}  — proxy to the task's dev server by looking
  up the port from DevServerManager. Works for both local and remote deployments.
- /api/preview-proxy?url=...          — proxy to an arbitrary URL (legacy).
"""

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request, Response

from daiflow.services.dev_server_service import dev_server_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preview-proxy"])

_STRIP_HEADERS = frozenset({
    "x-frame-options",
    "content-security-policy",
    "content-security-policy-report-only",
})

_HOP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
})

_FORWARD_REQUEST_HEADERS = (
    "accept", "accept-language", "cookie", "authorization",
    "user-agent", "range", "if-none-match", "content-type",
    "referer", "origin",
)

_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0)
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
        )
    return _client


async def shutdown_client():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


def _build_forwarded_headers(request: Request) -> dict[str, str]:
    headers = {}
    for key in _FORWARD_REQUEST_HEADERS:
        val = request.headers.get(key)
        if val:
            headers[key] = val
    return headers


def _filter_response_headers(upstream_headers) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in upstream_headers.multi_items():
        lower = key.lower()
        if lower in _STRIP_HEADERS or lower in _HOP_HEADERS or lower == "content-length":
            continue
        result[key] = value
    return result


async def _do_proxy(request: Request, target_url: str) -> Response:
    """Common proxy logic: forward request to target, strip security headers."""
    client = _get_client()
    headers = _build_forwarded_headers(request)

    body = None
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    try:
        upstream = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )
    except httpx.HTTPError as exc:
        logger.warning("Preview proxy error for %s: %s", target_url, exc)
        return Response(content=f"Upstream request failed: {exc}", status_code=502)

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_filter_response_headers(upstream.headers),
    )


# ── Built-in dev preview: /api/dev-preview/{task_id}/{path} ──

@router.api_route(
    "/api/dev-preview/{task_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def dev_preview(request: Request, task_id: str, path: str = ""):
    """Proxy to the task's local dev server by looking up port from DevServerManager."""
    status = dev_server_manager.status(task_id)
    if not status["running"]:
        return Response(content="Dev server is not running for this task", status_code=404)

    port = status["port"]
    qs = str(request.query_params)
    target = f"http://127.0.0.1:{port}/{path}"
    if qs:
        target += f"?{qs}"

    return await _do_proxy(request, target)


# ── Legacy URL proxy: /api/preview-proxy?url=... ──

@router.api_route(
    "/api/preview-proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
@router.api_route(
    "/api/preview-proxy",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def url_proxy(request: Request, url: str = ""):
    """Proxy to an arbitrary URL, stripping iframe-blocking headers."""
    if not url:
        return Response(content="Missing 'url' query parameter", status_code=400)

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return Response(content="Only http/https URLs are allowed", status_code=400)

    return await _do_proxy(request, url)
