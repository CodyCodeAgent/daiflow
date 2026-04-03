"""Skill Center API — CRUD for the global skill pool."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_db
from daiflow.exceptions import DaiFlowError
from daiflow.schemas import SkillBrief, SkillCreate, SkillResponse, SkillUpdate
from daiflow.services import skill_service

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _handle(e: DaiFlowError):
    from fastapi import HTTPException
    raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("", response_model=list[SkillBrief])
async def list_skills(
    source_type: str | None = Query(None),
    source_id: str | None = Query(None),
    project_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await skill_service.list_skills(
        db, source_type=source_type, source_id=source_id, project_id=project_id,
    )


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await skill_service.get_skill(db, skill_id)
    except DaiFlowError as e:
        _handle(e)


@router.post("", response_model=SkillResponse, status_code=201)
async def create_or_update_skill(data: SkillCreate, db: AsyncSession = Depends(get_db)):
    """Standard intake endpoint: upsert by (source_type, source_id, name)."""
    return await skill_service.upsert_skill(db, data)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(skill_id: str, data: SkillUpdate, db: AsyncSession = Depends(get_db)):
    try:
        return await skill_service.update_skill(
            db, skill_id, description=data.description, content=data.content,
        )
    except DaiFlowError as e:
        _handle(e)


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await skill_service.delete_skill(db, skill_id)
        return {"ok": True}
    except DaiFlowError as e:
        _handle(e)
