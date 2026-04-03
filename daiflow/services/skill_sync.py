"""Skill sync — write skills from DB to task directory for Cody SDK consumption."""

import re
import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import PROJECTS_DIR, TASKS_DIR, get_task_skills_dir
from daiflow.exceptions import NotFoundError
from daiflow.models import Skill, Task
from sqlalchemy import select


# ── SKILL.md assembly ──

_YAML_UNSAFE_RE = re.compile(r'[:\n\r#\[\]{}&*!|>\'"%@`]')


def assemble_skill_md(skill: Skill) -> str:
    """Assemble a Skill DB record into SKILL.md format with YAML frontmatter."""
    name = skill.name
    desc = skill.description
    # Quote YAML values if they contain unsafe characters
    if _YAML_UNSAFE_RE.search(name):
        name = f'"{name}"'
    if _YAML_UNSAFE_RE.search(desc):
        desc = f'"{desc}"'
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        f"user-invocable: false\n"
        f"---\n\n"
        f"{skill.content}"
    )


# ── SKILL.md parsing (for legacy file import) ──

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


# ── Sync: DB → task skill directory ──


async def sync_skills_to_task(db: AsyncSession, project_id: str, task_id: str) -> int:
    """Pull skills from DB, assemble SKILL.md files, and write to task skill dir.

    Falls back to legacy file-copy if no DB skills exist for the project.
    Also writes project.md to task root for backward compat.

    Returns the number of skills written.
    """
    from daiflow.services.skill_service import get_task_effective_skills

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
        _copy_project_md(project_id, task_id)

    return len(skills)


def _legacy_sync(project_id: str, task_id: str) -> int:
    """Legacy file-based sync for projects that haven't been re-initialized."""
    src = PROJECTS_DIR / project_id / "skills"
    dst = get_task_skills_dir(task_id)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        shutil.rmtree(dst)

    if src.exists():
        shutil.copytree(src, dst)
        count = sum(1 for d in dst.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
    else:
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
