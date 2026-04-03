"""Skill Center service — DB-backed skill management, assembly, and sync."""

import re
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import PROJECTS_DIR, TASKS_DIR
from daiflow.exceptions import NotFoundError
from daiflow.models import ProjectSkill, Skill, TaskSkill
from daiflow.schemas import SkillCreate


# ── Path helpers (unchanged) ──


def get_project_skills_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "skills"


def get_task_skills_dir(task_id: str) -> Path:
    return TASKS_DIR / task_id / ".cody" / "skills"


def get_task_dir(task_id: str) -> Path:
    d = TASKS_DIR / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_project_dir(project_id: str) -> Path:
    d = PROJECTS_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── SKILL.md parsing / assembly ──

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_FIELD_RE = re.compile(r"^(\w[\w-]*):\s*(.*)$", re.MULTILINE)


def parse_skill_md(content: str) -> tuple[str, str, str]:
    """Parse a SKILL.md file into (name, description, body).

    Returns ("", "", content) if no frontmatter is found.
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return ("", "", content)
    frontmatter = m.group(1)
    body = content[m.end():]
    fields: dict[str, str] = {}
    for fm in _FIELD_RE.finditer(frontmatter):
        fields[fm.group(1)] = fm.group(2).strip().strip("'\"")
    return (fields.get("name", ""), fields.get("description", ""), body.lstrip("\n"))


def assemble_skill_md(skill: Skill) -> str:
    """Assemble a Skill DB record into SKILL.md format with YAML frontmatter."""
    return (
        f"---\n"
        f"name: {skill.name}\n"
        f"description: {skill.description}\n"
        f"user-invocable: false\n"
        f"---\n\n"
        f"{skill.content}"
    )


# ── DB operations ──


async def upsert_skill(db: AsyncSession, data: SkillCreate) -> Skill:
    """Standard intake: create or update by (source_type, source_id, name).

    If source_type == "project", automatically creates a ProjectSkill link.
    """
    result = await db.execute(
        select(Skill).where(
            Skill.source_type == data.source_type,
            Skill.source_id == data.source_id,
            Skill.name == data.name,
        )
    )
    skill = result.scalar_one_or_none()

    if skill:
        skill.description = data.description
        skill.content = data.content
    else:
        skill = Skill(
            source_type=data.source_type,
            source_id=data.source_id,
            name=data.name,
            description=data.description,
            content=data.content,
        )
        db.add(skill)
        await db.flush()

    # Auto-link to project
    if data.source_type == "project" and data.source_id != "0":
        await _ensure_project_skill_link(db, data.source_id, skill.id)

    await db.commit()
    await db.refresh(skill)
    return skill


async def get_skill(db: AsyncSession, skill_id: str) -> Skill:
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise NotFoundError(f"Skill {skill_id} not found")
    return skill


async def list_skills(
    db: AsyncSession,
    *,
    source_type: str | None = None,
    source_id: str | None = None,
    project_id: str | None = None,
) -> list[Skill]:
    """List skills with optional filters.

    If project_id is given, returns skills linked to that project via project_skills.
    """
    if project_id:
        return await get_project_skills(db, project_id)
    q = select(Skill).order_by(Skill.updated_at.desc())
    if source_type:
        q = q.where(Skill.source_type == source_type)
    if source_id:
        q = q.where(Skill.source_id == source_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_skill(db: AsyncSession, skill_id: str, *, description: str | None = None, content: str | None = None) -> Skill:
    skill = await get_skill(db, skill_id)
    if description is not None:
        skill.description = description
    if content is not None:
        skill.content = content
    await db.commit()
    await db.refresh(skill)
    return skill


async def delete_skill(db: AsyncSession, skill_id: str) -> None:
    skill = await get_skill(db, skill_id)
    await db.delete(skill)
    await db.commit()


# ── Project-Skill associations ──


async def get_project_skills(db: AsyncSession, project_id: str) -> list[Skill]:
    result = await db.execute(
        select(Skill)
        .join(ProjectSkill, ProjectSkill.skill_id == Skill.id)
        .where(ProjectSkill.project_id == project_id)
        .order_by(Skill.name)
    )
    return list(result.scalars().all())


async def link_skill_to_project(db: AsyncSession, project_id: str, skill_id: str) -> None:
    await _ensure_project_skill_link(db, project_id, skill_id)
    await db.commit()


async def unlink_skill_from_project(db: AsyncSession, project_id: str, skill_id: str) -> None:
    result = await db.execute(
        select(ProjectSkill).where(
            ProjectSkill.project_id == project_id,
            ProjectSkill.skill_id == skill_id,
        )
    )
    link = result.scalar_one_or_none()
    if link:
        await db.delete(link)
        await db.commit()


async def _ensure_project_skill_link(db: AsyncSession, project_id: str, skill_id: str) -> None:
    result = await db.execute(
        select(ProjectSkill).where(
            ProjectSkill.project_id == project_id,
            ProjectSkill.skill_id == skill_id,
        )
    )
    if not result.scalar_one_or_none():
        db.add(ProjectSkill(project_id=project_id, skill_id=skill_id))
        await db.flush()


# ── Task-Skill associations ──


async def get_task_effective_skills(db: AsyncSession, task_id: str, project_id: str) -> list[Skill]:
    """Return the full set of skills for a task: project skills + task extra skills (deduplicated)."""
    project_skills = await get_project_skills(db, project_id)
    seen = {s.id for s in project_skills}

    result = await db.execute(
        select(Skill)
        .join(TaskSkill, TaskSkill.skill_id == Skill.id)
        .where(TaskSkill.task_id == task_id)
        .order_by(Skill.name)
    )
    extra = [s for s in result.scalars().all() if s.id not in seen]
    return project_skills + extra


async def get_task_extra_skills(db: AsyncSession, task_id: str) -> list[Skill]:
    result = await db.execute(
        select(Skill)
        .join(TaskSkill, TaskSkill.skill_id == Skill.id)
        .where(TaskSkill.task_id == task_id)
        .order_by(Skill.name)
    )
    return list(result.scalars().all())


async def add_task_skill(db: AsyncSession, task_id: str, skill_id: str) -> None:
    result = await db.execute(
        select(TaskSkill).where(
            TaskSkill.task_id == task_id,
            TaskSkill.skill_id == skill_id,
        )
    )
    if not result.scalar_one_or_none():
        db.add(TaskSkill(task_id=task_id, skill_id=skill_id))
        await db.commit()


async def remove_task_skill(db: AsyncSession, task_id: str, skill_id: str) -> None:
    result = await db.execute(
        select(TaskSkill).where(
            TaskSkill.task_id == task_id,
            TaskSkill.skill_id == skill_id,
        )
    )
    link = result.scalar_one_or_none()
    if link:
        await db.delete(link)
        await db.commit()


# ── Sync: DB → task skill directory ──


async def sync_skills_to_task(db: AsyncSession, project_id: str, task_id: str) -> int:
    """Pull skills from DB, assemble SKILL.md files, and write to task skill dir.

    Falls back to legacy file-copy if no DB skills exist for the project.
    Also writes project.md to task root for backward compatibility with prompts
    that reference it (sourced from the 'project-summary' skill in DB).

    Returns the number of skills written.
    """
    from daiflow.models import Task
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise NotFoundError(f"Task {task_id} not found")

    skills = await get_task_effective_skills(db, task_id, project_id)

    # Fallback: if no DB skills, use legacy file-copy
    if not skills:
        return _legacy_sync(project_id, task_id)

    task_skills_dir = get_task_skills_dir(task_id)
    # Clear and recreate
    if task_skills_dir.exists():
        shutil.rmtree(task_skills_dir)
    task_skills_dir.mkdir(parents=True, exist_ok=True)

    for skill in skills:
        skill_dir = task_skills_dir / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(assemble_skill_md(skill), encoding="utf-8")

    # Backward compat: write project.md to task root from 'project-summary' skill
    project_summary = next((s for s in skills if s.name == "project-summary"), None)
    if project_summary:
        task_dir = TASKS_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "project.md").write_text(project_summary.content, encoding="utf-8")
    else:
        # Legacy fallback: copy file-based project.md if it exists
        _copy_project_md(project_id, task_id)

    return len(skills)


def _legacy_sync(project_id: str, task_id: str) -> int:
    """Legacy file-based sync for projects that haven't been re-initialized."""
    import tempfile

    src = get_project_skills_dir(project_id)
    dst = get_task_skills_dir(task_id)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if src.exists():
        tmp = Path(tempfile.mkdtemp(dir=dst.parent))
        try:
            shutil.copytree(src, tmp / "_copy")
            if dst.exists():
                shutil.rmtree(dst)
            (tmp / "_copy").rename(dst)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        count = sum(1 for d in dst.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
    else:
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True, exist_ok=True)
        count = 0

    _copy_project_md(project_id, task_id)
    return count


def _copy_project_md(project_id: str, task_id: str) -> None:
    project_md_src = PROJECTS_DIR / project_id / "project.md"
    project_md_dst = TASKS_DIR / task_id / "project.md"
    if project_md_src.exists():
        project_md_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project_md_src, project_md_dst)
