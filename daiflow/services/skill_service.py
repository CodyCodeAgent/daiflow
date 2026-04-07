"""Skill Center service — DB operations, file sync, and tool factory."""

import logging
import re
import shutil

from sqlalchemy import delete, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import PROJECTS_DIR, TASKS_DIR, get_task_skills_dir
from daiflow.exceptions import NotFoundError
from daiflow.models import ProjectSkill, Skill, Task, TaskSkill
from daiflow.schemas import SkillCreate

logger = logging.getLogger(__name__)


# ── Generic link helpers ──


async def _ensure_link(db: AsyncSession, model, filters: dict, create_kwargs: dict) -> None:
    """Ensure a link record exists. Create it if missing."""
    q = select(model)
    for col, val in filters.items():
        q = q.where(getattr(model, col) == val)
    result = await db.execute(q)
    if not result.scalar_one_or_none():
        db.add(model(**create_kwargs))
        await db.flush()


async def _remove_link(db: AsyncSession, model, filters: dict) -> None:
    """Remove a link record if it exists."""
    q = select(model)
    for col, val in filters.items():
        q = q.where(getattr(model, col) == val)
    result = await db.execute(q)
    link = result.scalar_one_or_none()
    if link:
        await db.delete(link)


# ── Core CRUD ──


async def upsert_skill(db: AsyncSession, data: SkillCreate) -> Skill:
    """Standard intake: create or update by (source_type, source_id, name).

    If source_type == "project", automatically creates a ProjectSkill link.
    Does NOT commit — caller must commit.
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

    if data.source_type == "project" and data.source_id != "0":
        await _ensure_link(db, ProjectSkill,
            {"project_id": data.source_id, "skill_id": skill.id},
            {"project_id": data.source_id, "skill_id": skill.id})

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
    return skill


async def delete_skill(db: AsyncSession, skill_id: str) -> None:
    skill = await get_skill(db, skill_id)
    await db.delete(skill)


async def delete_project_skills(db: AsyncSession, project_id: str) -> None:
    """Delete all skills generated for a project (source_type='project')."""
    await db.execute(
        delete(Skill).where(Skill.source_type == "project", Skill.source_id == project_id)
    )


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
    await _ensure_link(db, ProjectSkill,
        {"project_id": project_id, "skill_id": skill_id},
        {"project_id": project_id, "skill_id": skill_id})


async def unlink_skill_from_project(db: AsyncSession, project_id: str, skill_id: str) -> None:
    await _remove_link(db, ProjectSkill, {"project_id": project_id, "skill_id": skill_id})


# ── Task-Skill associations ──


async def get_task_effective_skills(db: AsyncSession, task_id: str, project_id: str) -> list[Skill]:
    """Project skills + task extra skills in a single query."""
    project_skill_ids = select(ProjectSkill.skill_id).where(ProjectSkill.project_id == project_id)
    task_skill_ids = select(TaskSkill.skill_id).where(TaskSkill.task_id == task_id)
    combined = union(project_skill_ids, task_skill_ids).subquery()
    result = await db.execute(
        select(Skill).where(Skill.id.in_(select(combined.c.skill_id))).order_by(Skill.name)
    )
    return list(result.scalars().all())


async def get_task_extra_skills(db: AsyncSession, task_id: str) -> list[Skill]:
    result = await db.execute(
        select(Skill)
        .join(TaskSkill, TaskSkill.skill_id == Skill.id)
        .where(TaskSkill.task_id == task_id)
        .order_by(Skill.name)
    )
    return list(result.scalars().all())


async def add_task_skill(db: AsyncSession, task_id: str, skill_id: str) -> None:
    await _ensure_link(db, TaskSkill,
        {"task_id": task_id, "skill_id": skill_id},
        {"task_id": task_id, "skill_id": skill_id})


async def remove_task_skill(db: AsyncSession, task_id: str, skill_id: str) -> None:
    await _remove_link(db, TaskSkill, {"task_id": task_id, "skill_id": skill_id})


# ── save_skill tool factory ──


def make_save_skill_tool(db_holder: list, project_id: str):
    """Create a save_skill custom tool function for Cody SDK.

    db_holder is a single-element list holding the AsyncSession, allowing the
    closure to reference the session alive during the agent run.
    """
    async def save_skill(ctx, name: str, description: str, content: str) -> str:
        """Save a knowledge skill to the Skill Center database. Call this tool to persist your analysis output."""
        try:
            if not name or not name.strip():
                return "Error: Skill name cannot be empty"
            await upsert_skill(db_holder[0], SkillCreate(
                source_type="project",
                source_id=project_id,
                name=name.strip(),
                description=description.strip(),
                content=content.strip(),
            ))
            # NOTE: commit here is intentional — this tool is called by the AI agent,
            # not by a router. Each tool invocation must be self-contained because
            # the agent may call other tools after this one returns.
            await db_holder[0].commit()
            return f"Skill '{name.strip()}' saved successfully."
        except Exception as e:
            logger.error("save_skill tool failed for %s/%s: %s", project_id, name, e)
            return f"Error saving skill: {e}"
    return save_skill


# ── Content injection helper ──


async def get_project_skills_content(db: AsyncSession, project_id: str, *, max_skills: int = 50, max_total: int = 500_000) -> str:
    """Build a text block with all existing skills for injection into prompts."""
    skills = await get_project_skills(db, project_id)
    if not skills:
        return "(No skills generated yet)"
    parts = []
    total = 0
    for s in skills[:max_skills]:
        part = f"### {s.name}\n**Description:** {s.description}\n\n{s.content}"
        total += len(part)
        if total > max_total:
            parts.append("... (remaining skills truncated)")
            break
        parts.append(part)
    return "\n\n---\n\n".join(parts)


# ── SKILL.md assembly (for task sync) ──

_YAML_UNSAFE_RE = re.compile(r'[:\n\r#\[\]{}&*!|>\'"%@`]')


def assemble_skill_md(skill: Skill) -> str:
    """Assemble a Skill DB record into SKILL.md format with YAML frontmatter."""
    name = skill.name
    desc = skill.description
    if _YAML_UNSAFE_RE.search(name):
        name = f'"{name}"'
    if _YAML_UNSAFE_RE.search(desc):
        desc = f'"{desc}"'
    return f"---\nname: {name}\ndescription: {desc}\nuser-invocable: false\n---\n\n{skill.content}"


# ── Sync: DB → task skill directory ──


async def sync_skills_to_task(db: AsyncSession, project_id: str, task_id: str) -> int:
    """Pull skills from DB, assemble SKILL.md files, and write to task skill dir.

    Also writes project.md to task root for backward compat.
    Returns the number of skills written.
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise NotFoundError(f"Task {task_id} not found")

    skills = await get_task_effective_skills(db, task_id, project_id)
    if not skills:
        return 0

    task_skills_dir = get_task_skills_dir(task_id)
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

    return len(skills)


async def sync_skills_to_dir(db: AsyncSession, project_id: str, skills_dir) -> int:
    """Write project skills as SKILL.md files to an arbitrary directory.

    Used by conversations (and anything else that needs project skills without
    task-specific extras). Returns the number of skills written.
    """
    from pathlib import Path
    skills_dir = Path(skills_dir)

    skills = await get_project_skills(db, project_id)
    if not skills:
        return 0

    if skills_dir.exists():
        shutil.rmtree(skills_dir)
    skills_dir.mkdir(parents=True, exist_ok=True)

    for skill in skills:
        skill_subdir = skills_dir / skill.name
        skill_subdir.mkdir(parents=True, exist_ok=True)
        (skill_subdir / "SKILL.md").write_text(assemble_skill_md(skill), encoding="utf-8")

    return len(skills)
