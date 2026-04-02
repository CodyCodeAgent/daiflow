import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_db
from daiflow.exceptions import DaiFlowError
from daiflow.models import RunnerConfig, Setting
from daiflow.schemas import (
    ConnectionTest,
    DefaultRunnerUpdate,
    McpServerCreate,
    McpServerResponse,
    McpServerTest,
    McpServerUpdate,
    RunnerConfigCreate,
    RunnerConfigResponse,
    RunnerConfigUpdate,
    SettingsUpdate,
)
from daiflow.services import mcp_service

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)

SETTING_KEYS = ["cody_model", "cody_base_url", "cody_api_key", "theme", "language", "tool_approval_mode"]
@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting))
    settings = {s.key: s.value for s in result.scalars().all()}
    # Mask secrets - never return raw values
    for secret_key in ("cody_api_key",):
        if secret_key in settings and settings[secret_key]:
            val = settings[secret_key]
            if len(val) > 8:
                settings[secret_key] = val[:4] + "*" * (len(val) - 8) + val[-4:]
            else:
                settings[secret_key] = "****"
    return settings


@router.put("")
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    updates = data.model_dump(exclude_none=True)
    # Validate required AI fields are not empty
    required_keys = {"cody_model", "cody_base_url", "cody_api_key"}
    for key in required_keys:
        if key in updates and not updates[key].strip():
            raise HTTPException(
                status_code=400,
                detail=f"Field '{key}' cannot be empty",
            )
    # Skip secret updates if the value is a masked placeholder
    for secret_key in ("cody_api_key",):
        if secret_key in updates and "****" in updates[secret_key]:
            del updates[secret_key]

    for key, value in updates.items():
        existing = await db.get(Setting, key)
        if existing:
            existing.value = value
        else:
            db.add(Setting(key=key, value=value))
    await db.commit()
    return {"ok": True}


@router.get("/check")
async def check_settings(db: AsyncSession = Depends(get_db)):
    """Check if AI model is configured. Returns {configured: bool}.

    Configured if any of:
    - At least one RunnerConfig record exists, OR
    - Legacy Cody settings (cody_model, cody_base_url, cody_api_key) are all present.
    """
    # Check for RunnerConfig records
    runner_result = await db.execute(select(RunnerConfig).limit(1))
    has_runner_configs = runner_result.scalar_one_or_none() is not None

    if has_runner_configs:
        # Resolve the active default runner name for display
        default_setting = await db.get(Setting, "default_runner_id")
        default_name = ""
        if default_setting and default_setting.value:
            rc = await db.get(RunnerConfig, default_setting.value)
            if rc:
                default_name = rc.name
        return {"configured": True, "model": default_name}

    # Legacy Cody settings fallback
    result = await db.execute(
        select(Setting).where(Setting.key.in_(["cody_model", "cody_base_url", "cody_api_key"]))
    )
    settings = {s.key: s.value for s in result.scalars().all()}
    configured = all(settings.get(k) for k in ["cody_model", "cody_base_url", "cody_api_key"])
    return {"configured": configured, "model": settings.get("cody_model", "")}


@router.post("/test")
async def test_connection(data: ConnectionTest, db: AsyncSession = Depends(get_db)):
    """Test AI model connection with the provided credentials (without saving)."""
    import tempfile

    from cody import Cody

    # If api_key is masked, resolve the real key from DB
    api_key = data.cody_api_key
    if "****" in api_key:
        result = await db.execute(
            select(Setting).where(Setting.key == "cody_api_key")
        )
        row = result.scalar_one_or_none()
        if not row or not row.value:
            raise HTTPException(status_code=400, detail="API key not found. Please enter a new key.")
        api_key = row.value

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = (
                Cody()
                .workdir(tmpdir)
                .model(data.cody_model)
                .base_url(data.cody_base_url)
                .api_key(api_key)
                .build()
            )
            async with client:
                await asyncio.wait_for(client.run("hi"), timeout=15)
        return {"ok": True, "model": data.cody_model}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=422, detail="Connection timed out. Please check the API URL and network.")
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "403" in msg or "auth" in msg or "unauthorized" in msg:
            detail = "Authentication failed. Please check the API key."
        elif "404" in msg or "not found" in msg or "model" in msg:
            detail = f"Model not found: {data.cody_model}. Please check the model name."
        elif "connect" in msg or "resolve" in msg or "refused" in msg:
            detail = "Cannot connect to the API URL. Please check the URL."
        else:
            detail = str(e)
        logger.warning("Connection test failed: %s", e)
        raise HTTPException(status_code=422, detail=detail)



# ── Runner Configs ──


def _runner_to_response(rc: RunnerConfig, default_runner_id: str | None) -> RunnerConfigResponse:
    """Convert a RunnerConfig ORM object to a response schema (api_key masked)."""
    return RunnerConfigResponse(
        id=rc.id,
        type=rc.type,
        name=rc.name,
        config=json.loads(rc.config) if rc.config else {},
        is_default=(rc.id == default_runner_id) if default_runner_id else False,
        created_at=rc.created_at,
        updated_at=rc.updated_at,
    )


async def _get_default_runner_id(db: AsyncSession) -> str | None:
    setting = await db.get(Setting, "default_runner_id")
    return setting.value if setting and setting.value else None


@router.get("/runners", response_model=list[RunnerConfigResponse])
async def list_runners(db: AsyncSession = Depends(get_db)):
    """List all configured runners with api_key masked."""
    result = await db.execute(select(RunnerConfig).order_by(RunnerConfig.created_at))
    runners = result.scalars().all()
    default_id = await _get_default_runner_id(db)
    return [_runner_to_response(rc, default_id) for rc in runners]


@router.get("/runners/default")
async def get_default_runner(db: AsyncSession = Depends(get_db)):
    """Get the current global default runner id."""
    runner_id = await _get_default_runner_id(db)
    return {"runner_id": runner_id}


@router.put("/runners/default")
async def set_default_runner(data: DefaultRunnerUpdate, db: AsyncSession = Depends(get_db)):
    """Set the global default runner."""
    rc = await db.get(RunnerConfig, data.runner_id)
    if not rc:
        raise HTTPException(status_code=404, detail=f"Runner '{data.runner_id}' not found")
    setting = await db.get(Setting, "default_runner_id")
    if setting:
        setting.value = data.runner_id
    else:
        db.add(Setting(key="default_runner_id", value=data.runner_id))
    await db.commit()
    return {"ok": True, "runner_id": data.runner_id}


@router.post("/runners", response_model=RunnerConfigResponse)
async def create_runner(data: RunnerConfigCreate, db: AsyncSession = Depends(get_db)):
    """Create a new runner configuration."""
    rc = RunnerConfig(
        type=data.type,
        name=data.name,
        config=json.dumps(data.config),
    )
    db.add(rc)
    await db.commit()
    await db.refresh(rc)

    # If this is the first runner, auto-set as default
    result = await db.execute(select(RunnerConfig))
    count = len(result.scalars().all())
    if count == 1:
        db.add(Setting(key="default_runner_id", value=rc.id))
        await db.commit()

    default_id = await _get_default_runner_id(db)
    return _runner_to_response(rc, default_id)


@router.put("/runners/{runner_id}", response_model=RunnerConfigResponse)
async def update_runner(runner_id: str, data: RunnerConfigUpdate, db: AsyncSession = Depends(get_db)):
    """Update a runner configuration."""
    rc = await db.get(RunnerConfig, runner_id)
    if not rc:
        raise HTTPException(status_code=404, detail=f"Runner '{runner_id}' not found")

    if data.name is not None:
        rc.name = data.name
    if data.config is not None:
        # Merge: keep existing api_key if the new value is masked
        existing_cfg = json.loads(rc.config) if rc.config else {}
        new_cfg = dict(data.config)
        if "api_key" in new_cfg and "****" in str(new_cfg.get("api_key", "")):
            new_cfg["api_key"] = existing_cfg.get("api_key", "")
        rc.config = json.dumps({**existing_cfg, **new_cfg})

    await db.commit()
    await db.refresh(rc)
    default_id = await _get_default_runner_id(db)
    return _runner_to_response(rc, default_id)


@router.delete("/runners/{runner_id}")
async def delete_runner(runner_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a runner configuration. Projects/tasks with this runner fall back to default."""
    rc = await db.get(RunnerConfig, runner_id)
    if not rc:
        raise HTTPException(status_code=404, detail=f"Runner '{runner_id}' not found")

    # Clear default if this was the default runner
    default_id = await _get_default_runner_id(db)
    if default_id == runner_id:
        setting = await db.get(Setting, "default_runner_id")
        if setting:
            setting.value = ""
            await db.commit()

    await db.delete(rc)
    await db.commit()
    return {"ok": True}


@router.post("/runners/{runner_id}/test")
async def test_runner_connection(runner_id: str, db: AsyncSession = Depends(get_db)):
    """Test connectivity of an existing runner config (without saving changes)."""
    rc = await db.get(RunnerConfig, runner_id)
    if not rc:
        raise HTTPException(status_code=404, detail=f"Runner '{runner_id}' not found")
    return await _test_runner_config(rc.type, json.loads(rc.config) if rc.config else {})


@router.post("/runners/test-config")
async def test_runner_config_endpoint(data: RunnerConfigCreate, db: AsyncSession = Depends(get_db)):
    """Test a runner config before saving (used during add/edit modal)."""
    return await _test_runner_config(data.type, data.config)


async def _test_runner_config(runner_type: str, config: dict) -> dict:
    """Shared connectivity test logic for all runner types."""
    import tempfile

    if runner_type == "cody":
        from cody import Cody
        model = config.get("model", "")
        base_url = config.get("base_url", "")
        api_key = config.get("api_key", "")
        if not all([model, base_url, api_key]):
            raise HTTPException(status_code=400, detail="model, base_url, and api_key are required for Cody runner")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                client = (
                    Cody()
                    .workdir(tmpdir)
                    .model(model)
                    .base_url(base_url)
                    .api_key(api_key)
                    .build()
                )
                async with client:
                    await asyncio.wait_for(client.run("hi"), timeout=15)
            return {"ok": True, "type": runner_type}
        except asyncio.TimeoutError:
            raise HTTPException(status_code=422, detail="Connection timed out.")
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))

    elif runner_type == "claude_code":
        try:
            import subprocess
            result = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
            if result.returncode != 0:
                raise HTTPException(status_code=422, detail="claude CLI not found or not working")
            return {"ok": True, "type": runner_type}
        except FileNotFoundError:
            raise HTTPException(
                status_code=422,
                detail="Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
            )
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))

    elif runner_type == "cursor":
        try:
            import subprocess
            result = subprocess.run(["agent", "--version"], capture_output=True, timeout=5)
            if result.returncode != 0:
                raise HTTPException(status_code=422, detail="Cursor agent CLI not found or not working")
            return {"ok": True, "type": runner_type}
        except FileNotFoundError:
            raise HTTPException(status_code=422, detail="Cursor agent CLI not found. Install cursor CLI.")
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))

    else:
        raise HTTPException(status_code=400, detail=f"Unknown runner type: {runner_type!r}")


# ── MCP Servers ──


@router.post("/mcp-servers/test")
async def test_mcp_server(data: McpServerTest):
    """Test MCP server connectivity by sending a JSON-RPC initialize request."""
    try:
        return await mcp_service.test_server(data.url, data.headers)
    except DaiFlowError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/mcp-servers", response_model=list[McpServerResponse])
async def list_mcp_servers(db: AsyncSession = Depends(get_db)):
    servers = await mcp_service.list_servers(db)
    return [McpServerResponse.model_validate(s) for s in servers]


@router.post("/mcp-servers", response_model=McpServerResponse)
async def create_mcp_server(data: McpServerCreate, db: AsyncSession = Depends(get_db)):
    try:
        server = await mcp_service.create_server(db, data.name, data.url, data.headers, data.enabled)
        return McpServerResponse.model_validate(server)
    except DaiFlowError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.put("/mcp-servers/{server_id}", response_model=McpServerResponse)
async def update_mcp_server(server_id: str, data: McpServerUpdate, db: AsyncSession = Depends(get_db)):
    try:
        server = await mcp_service.update_server(db, server_id, data.model_dump(exclude_none=True))
        return McpServerResponse.model_validate(server)
    except DaiFlowError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.delete("/mcp-servers/{server_id}")
async def delete_mcp_server(server_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await mcp_service.delete_server(db, server_id)
        return {"ok": True}
    except DaiFlowError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
