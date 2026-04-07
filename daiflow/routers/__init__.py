"""Shared router utilities."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.models import Conversation, Project, Task, Todo


async def get_or_404(db: AsyncSession, model, entity_id: str, label: str = "Entity"):
    """Fetch an entity by primary key or raise 404."""
    entity = await db.get(model, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return entity


async def get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    return await get_or_404(db, Project, project_id, "Project")


async def get_task_or_404(db: AsyncSession, task_id: str) -> Task:
    return await get_or_404(db, Task, task_id, "Task")


async def get_todo_or_404(db: AsyncSession, todo_id: str) -> Todo:
    return await get_or_404(db, Todo, todo_id, "Todo")


async def get_conversation_or_404(db: AsyncSession, conv_id: str) -> Conversation:
    return await get_or_404(db, Conversation, conv_id, "Conversation")
