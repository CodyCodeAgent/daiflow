"""Skill Center API — CRUD + project/task associations."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_db
from daiflow.exceptions import DaiFlowError
from daiflow.models import Project, Task
from daiflow.schemas import SkillBrief, SkillCreate, SkillResponse, SkillUpdate
from daiflow.services import skill_service

# Use /api prefix (not /api/skills) because this router also serves
# /api/projects/{id}/skills and /api/tasks/{id}/skills — consolidating
# all skill-related routes in one file for cohesion.
router = APIRouter(prefix="/api", tags=["skills"])


# ── Helpers ──

async def _get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_task_or_404(db: AsyncSession, task_id: str) -> Task:
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _handle(e: DaiFlowError):
    raise HTTPException(status_code=e.status_code, detail=str(e))


# ── Skill CRUD ──


@router.get("/skills", response_model=list[SkillBrief])
async def list_skills(
    source_type: str | None = Query(None),
    source_id: str | None = Query(None),
    project_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await skill_service.list_skills(
        db, source_type=source_type, source_id=source_id, project_id=project_id,
    )


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await skill_service.get_skill(db, skill_id)
    except DaiFlowError as e:
        _handle(e)


@router.post("/skills", response_model=SkillResponse, status_code=201)
async def create_or_update_skill(data: SkillCreate, db: AsyncSession = Depends(get_db)):
    """Standard intake endpoint: upsert by (source_type, source_id, name)."""
    if data.source_type == "project" and data.source_id != "0":
        await _get_project_or_404(db, data.source_id)
    skill = await skill_service.upsert_skill(db, data)
    await db.commit()
    await db.refresh(skill)
    return skill


@router.put("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(skill_id: str, data: SkillUpdate, db: AsyncSession = Depends(get_db)):
    try:
        skill = await skill_service.update_skill(
            db, skill_id, description=data.description, content=data.content,
        )
        await db.commit()
        await db.refresh(skill)
        return skill
    except DaiFlowError as e:
        _handle(e)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await skill_service.delete_skill(db, skill_id)
        await db.commit()
    except DaiFlowError as e:
        _handle(e)


# ── Project-Skill associations ──


@router.get("/projects/{project_id}/skills", response_model=list[SkillBrief])
async def get_project_skills(project_id: str, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    return await skill_service.get_project_skills(db, project_id)


@router.post("/projects/{project_id}/skills/{skill_id}")
async def link_project_skill(project_id: str, skill_id: str, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    try:
        await skill_service.get_skill(db, skill_id)
    except DaiFlowError as e:
        _handle(e)
    await skill_service.link_skill_to_project(db, project_id, skill_id)
    await db.commit()
    return {"ok": True}


@router.delete("/projects/{project_id}/skills/{skill_id}")
async def unlink_project_skill(project_id: str, skill_id: str, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    await skill_service.unlink_skill_from_project(db, project_id, skill_id)
    await db.commit()
    return {"ok": True}


# ── Task-Skill associations ──


@router.get("/tasks/{task_id}/skills")
async def get_task_skills(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await _get_task_or_404(db, task_id)
    project_skills = await skill_service.get_project_skills(db, task.project_id)
    extra_skills = await skill_service.get_task_extra_skills(db, task_id)
    return {
        "project_skills": [SkillBrief.model_validate(s) for s in project_skills],
        "extra_skills": [SkillBrief.model_validate(s) for s in extra_skills],
    }


@router.post("/tasks/{task_id}/skills/{skill_id}")
async def add_task_skill(task_id: str, skill_id: str, db: AsyncSession = Depends(get_db)):
    await _get_task_or_404(db, task_id)
    try:
        await skill_service.get_skill(db, skill_id)
    except DaiFlowError as e:
        _handle(e)
    await skill_service.add_task_skill(db, task_id, skill_id)
    await db.commit()
    return {"ok": True}


@router.delete("/tasks/{task_id}/skills/{skill_id}")
async def remove_task_skill(task_id: str, skill_id: str, db: AsyncSession = Depends(get_db)):
    await _get_task_or_404(db, task_id)
    await skill_service.remove_task_skill(db, task_id, skill_id)
    await db.commit()
    return {"ok": True}
