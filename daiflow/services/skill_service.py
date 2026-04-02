import json
import shutil
import tempfile
from pathlib import Path

from daiflow.config import PROJECTS_DIR, TASKS_DIR


def get_project_skills_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "skills"


def get_task_skills_dir(task_id: str) -> Path:
    return TASKS_DIR / task_id / ".cody" / "skills"


def _sync_dir(src: Path, dst: Path) -> None:
    """Atomically replace dst with a fresh copy of src.

    If src does not exist, dst is cleared (or not created).
    """
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
    else:
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True, exist_ok=True)


def sync_skills_to_task(project_id: str, task_id: str):
    """Copy project skills to task .cody/skills/ directory."""
    _sync_dir(get_project_skills_dir(project_id), get_task_skills_dir(task_id))

    # Also copy project.md if it exists
    project_md_src = PROJECTS_DIR / project_id / "project.md"
    project_md_dst = TASKS_DIR / task_id / "project.md"
    if project_md_src.exists():
        shutil.copy2(project_md_src, project_md_dst)


def get_task_dir(task_id: str) -> Path:
    d = TASKS_DIR / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_project_dir(project_id: str) -> Path:
    d = PROJECTS_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d
