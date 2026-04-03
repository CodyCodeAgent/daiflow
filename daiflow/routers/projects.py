import asyncio
import json
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from daiflow.config import PROJECTS_DIR
from daiflow.database import get_db
from daiflow.models import Project, ProjectRepo, Session, SessionStatus, Task, TaskStatus
from daiflow.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from daiflow.services.project_service import (
    get_init_layer_status, prepare_init_sessions, run_init, run_init_retry,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])

# Task statuses that indicate active development (block knowledge regeneration)
_ACTIVE_TASK_STATUSES = [
    TaskStatus.INITIALIZING,
    TaskStatus.PLANNING,
    TaskStatus.PLAN_LOCKED,
    TaskStatus.TODO_READY,
    TaskStatus.CODING,
    TaskStatus.REVIEWING,
]


async def _check_no_active_tasks(db: AsyncSession, project_id: str):
    """Raise 409 if the project has tasks in active development."""
    result = await db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.status.in_(_ACTIVE_TASK_STATUSES),
        )
    )
    active = result.scalars().first()
    if active:
        raise HTTPException(
            status_code=409,
            detail="Project has active tasks in development. Please wait for them to finish before regenerating knowledge.",
        )


async def _get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    """Look up a project by ID, raise 404 if not found."""
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


def _project_to_dict(p: Project, repos: list | None = None) -> dict:
    """Serialize a Project + repos to dict. Repos must be passed explicitly to avoid lazy loading."""
    return ProjectResponse.model_validate({
        "id": p.id, "name": p.name, "description": p.description,
        "skill_names": p.skill_names, "repos": repos or [],
        "runner_id": p.runner_id,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }).model_dump()


@router.get("")
async def list_projects(db: AsyncSession = Depends(get_db)):
    # Fix N+1: use selectinload to eagerly load repos
    result = await db.execute(
        select(Project).options(selectinload(Project.repos)).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
    return [_project_to_dict(p, p.repos) for p in projects]


@router.get("/{project_id}")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    p = await _get_project_or_404(db, project_id)
    repos_result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == p.id)
    )
    return _project_to_dict(p, repos_result.scalars().all())


@router.post("")
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(
        name=data.name,
        description=data.description,
        skill_names=json.dumps(data.skill_names),
        runner_id=data.runner_id,
    )
    db.add(project)
    await db.flush()

    for r in data.repos:
        repo = ProjectRepo(
            project_id=project.id,
            git_url=r.git_url,
            local_path=r.local_path,
            repo_type=r.repo_type,
            repo_type_label=r.repo_type_label,
            description=r.description,
            dev_command=r.dev_command,
            dev_port=r.dev_port,
            dev_preview_url=r.dev_preview_url,
            sub_path=r.sub_path,
        )
        db.add(repo)

    await db.commit()

    repos_result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == project.id)
    )
    return _project_to_dict(project, repos_result.scalars().all())


@router.put("/{project_id}")
async def update_project(
    project_id: str, data: ProjectUpdate, db: AsyncSession = Depends(get_db)
):
    project = await _get_project_or_404(db, project_id)

    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    if data.skill_names is not None:
        project.skill_names = json.dumps(data.skill_names)
    if data.runner_id is not None:
        project.runner_id = data.runner_id

    if data.repos is not None:
        # Diff repos: update existing, add new, delete removed
        old_repos_result = await db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == project_id)
        )
        old_repos = {r.id: r for r in old_repos_result.scalars().all()}

        # Build set of incoming repo IDs (repos with an id field are existing)
        seen_ids: set[str] = set()
        for r in data.repos:
            # Match by local_path + git_url to find existing repo
            matched = None
            for old in old_repos.values():
                if old.id not in seen_ids and old.local_path == r.local_path and old.git_url == r.git_url:
                    matched = old
                    break

            if matched:
                seen_ids.add(matched.id)
                matched.repo_type = r.repo_type
                matched.repo_type_label = r.repo_type_label
                matched.description = r.description
                matched.dev_command = r.dev_command
                matched.dev_port = r.dev_port
                matched.dev_preview_url = r.dev_preview_url
                matched.sub_path = r.sub_path
            else:
                repo = ProjectRepo(
                    project_id=project_id,
                    git_url=r.git_url,
                    local_path=r.local_path,
                    repo_type=r.repo_type,
                    repo_type_label=r.repo_type_label,
                    description=r.description,
                    dev_command=r.dev_command,
                    dev_port=r.dev_port,
                    dev_preview_url=r.dev_preview_url,
                    sub_path=r.sub_path,
                )
                db.add(repo)

        # Delete repos that are no longer in the list
        for old_id, old_repo in old_repos.items():
            if old_id not in seen_ids:
                await db.delete(old_repo)

    await db.commit()

    repos_result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == project_id)
    )
    return _project_to_dict(project, repos_result.scalars().all())


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await _get_project_or_404(db, project_id)

    await db.delete(project)
    await db.commit()

    # Clean up local directory
    project_dir = PROJECTS_DIR / project_id
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)

    return {"ok": True}


@router.post("/{project_id}/init")
async def init_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger project knowledge generation. Returns list of session records."""
    project = await _get_project_or_404(db, project_id)

    await _check_no_active_tasks(db, project_id)

    repos_result = await db.execute(
        select(ProjectRepo).where(ProjectRepo.project_id == project_id)
    )
    repos = repos_result.scalars().all()

    # Delegate session pre-creation to service layer
    session_defs = await prepare_init_sessions(db, project_id, repos)

    # Start background init with independent DB session
    background_tasks.add_task(run_init, project_id)

    return session_defs


@router.post("/{project_id}/init/retry")
async def retry_init(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Retry failed init sessions + re-run all subsequent layers."""
    project = await _get_project_or_404(db, project_id)

    await _check_no_active_tasks(db, project_id)

    # Find failed sessions
    result = await db.execute(
        select(Session).where(
            Session.ref_id == project_id,
            Session.type == "init",
            Session.status == SessionStatus.FAILED,
        )
    )
    failed = result.scalars().all()
    if not failed:
        raise HTTPException(status_code=400, detail="No failed sessions to retry")

    # Determine the earliest failed layer
    from_layer = min(s.layer for s in failed if s.layer is not None)
    failed_ids = [s.session_id for s in failed if s.layer == from_layer]

    # Reset failed sessions in from_layer to waiting
    for s in failed:
        if s.layer == from_layer:
            s.status = SessionStatus.WAITING
            s.error = None
            s.started_at = None
            s.finished_at = None

    # Reset ALL sessions in subsequent layers to waiting
    subsequent = await db.execute(
        select(Session).where(
            Session.ref_id == project_id,
            Session.type == "init",
            Session.layer > from_layer,
        )
    )
    for s in subsequent.scalars().all():
        s.status = SessionStatus.WAITING
        s.error = None
        s.started_at = None
        s.finished_at = None

    await db.commit()

    background_tasks.add_task(run_init_retry, project_id, failed_ids, from_layer)

    return {"ok": True, "from_layer": from_layer, "failed_session_ids": failed_ids}


@router.get("/{project_id}/init/sessions")
async def get_init_sessions(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get all init sessions grouped by layer with aggregate status."""
    return await get_init_layer_status(db, project_id)


@router.get("/{project_id}/knowledge")
async def get_project_knowledge(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get project knowledge files (project.md + skills)."""
    project = await _get_project_or_404(db, project_id)

    project_dir = PROJECTS_DIR / project_id
    files: list[dict] = []

    def _read_knowledge():
        result = []
        # project.md
        project_md = project_dir / "project.md"
        if project_md.exists():
            result.append({
                "name": "project.md",
                "type": "index",
                "content": project_md.read_text(encoding="utf-8"),
            })

        # skills
        skills_dir = project_dir / "skills"
        if skills_dir.exists():
            for skill_dir in sorted(skills_dir.iterdir()):
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    result.append({
                        "name": skill_dir.name,
                        "type": "skill",
                        "content": skill_file.read_text(encoding="utf-8") if skill_file.exists() else "",
                    })
        return result

    files = await asyncio.to_thread(_read_knowledge)
    return {"project_id": project_id, "files": files}


