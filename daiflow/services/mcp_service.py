"""MCP server management service."""

import json
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.exceptions import DaiFlowError, NotFoundError
from daiflow.models import McpServer

logger = logging.getLogger(__name__)


async def get_active_mcp_servers(db: AsyncSession) -> list[tuple[str, str, dict[str, str]]]:
    """Return all enabled user-configured MCP servers as (name, url, headers) tuples."""
    servers: list[tuple[str, str, dict[str, str]]] = []

    result = await db.execute(select(McpServer).where(McpServer.enabled == 1))
    for srv in result.scalars().all():
        headers = json.loads(srv.headers) if srv.headers else {}
        servers.append((srv.name, srv.url, headers))

    return servers


async def list_servers(db: AsyncSession) -> list[McpServer]:
    """Return all user-configured MCP servers ordered by creation time."""
    result = await db.execute(select(McpServer).order_by(McpServer.created_at))
    return list(result.scalars().all())


async def create_server(
    db: AsyncSession, name: str, url: str, headers: dict, enabled: bool = True,
) -> McpServer:
    """Create a new MCP server entry. Raises on duplicate name."""
    existing = await db.execute(select(McpServer).where(McpServer.name == name))
    if existing.scalar_one_or_none():
        raise DaiFlowError(f"MCP server '{name}' already exists")

    server = McpServer(
        name=name,
        url=url,
        headers=json.dumps(headers),
        enabled=1 if enabled else 0,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return server


async def update_server(
    db: AsyncSession, server_id: str, updates: dict,
) -> McpServer:
    """Update an MCP server. Raises NotFoundError / DaiFlowError on conflicts."""
    server = await db.get(McpServer, server_id)
    if not server:
        raise NotFoundError("MCP server not found")

    if "name" in updates:
        dup = await db.execute(
            select(McpServer).where(McpServer.name == updates["name"], McpServer.id != server_id)
        )
        if dup.scalar_one_or_none():
            raise DaiFlowError(f"MCP server '{updates['name']}' already exists")
        server.name = updates["name"]
    if "url" in updates:
        server.url = updates["url"]
    if "headers" in updates:
        server.headers = json.dumps(updates["headers"])
    if "enabled" in updates:
        server.enabled = 1 if updates["enabled"] else 0

    await db.commit()
    await db.refresh(server)
    return server


async def delete_server(db: AsyncSession, server_id: str) -> None:
    """Delete an MCP server by ID."""
    server = await db.get(McpServer, server_id)
    if not server:
        raise NotFoundError("MCP server not found")
    await db.delete(server)
    await db.commit()


async def test_server(url: str, headers: dict[str, str]) -> dict:
    """Test MCP server connectivity via JSON-RPC initialize request."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "daiflow", "version": "0.1.0"},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                url,
                json=payload,
                headers={**headers, "Content-Type": "application/json"},
            )
        body = resp.json()
        if "result" in body:
            server_info = body["result"].get("serverInfo", {})
            return {
                "ok": True,
                "server_name": server_info.get("name", ""),
                "server_version": server_info.get("version", ""),
                "protocol_version": body["result"].get("protocolVersion", ""),
            }
        elif "error" in body:
            detail = body["error"].get("message", str(body["error"]))
            raise DaiFlowError(f"MCP server error: {detail}", status_code=422)
        else:
            raise DaiFlowError("Unexpected response format from MCP server", status_code=422)
    except httpx.TimeoutException:
        raise DaiFlowError("Connection timed out. Check the URL and network.", status_code=422)
    except httpx.ConnectError:
        raise DaiFlowError("Cannot connect to the URL. Check the address.", status_code=422)
    except DaiFlowError:
        raise
    except Exception as e:
        logger.warning("MCP test failed: %s", e)
        raise DaiFlowError(str(e), status_code=422)
