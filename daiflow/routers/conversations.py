"""Conversations CRUD + init endpoints."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.database import get_db
from daiflow.models import Conversation, ConversationStatus, Project, Session
from daiflow.routers import get_conversation_or_404, get_project_or_404
from daiflow.schemas import ConversationCreate, ConversationResponse
from daiflow.services.conversation_service import delete_conversation_dir, init_conversation
from daiflow.session_ids import conversation_init_fetch, conversation_init_skills

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _conv_to_dict(c: Conversation) -> dict:
    return ConversationResponse.model_validate(c).model_dump()


# ── CRUD ──


@router.get("")
async def list_conversations(
    project_id: str | None = None, db: AsyncSession = Depends(get_db)
):
    query = select(Conversation).order_by(Conversation.created_at.desc())
    if project_id:
        query = query.where(Conversation.project_id == project_id)
    result = await db.execute(query)
    return [_conv_to_dict(c) for c in result.scalars().all()]


@router.get("/{conv_id}")
async def get_conversation(conv_id: str, db: AsyncSession = Depends(get_db)):
    conv = await get_conversation_or_404(db, conv_id)
    return _conv_to_dict(conv)


@router.post("")
async def create_conversation(
    data: ConversationCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Validate project exists
    await get_project_or_404(db, data.project_id)

    conv = Conversation(
        name=data.name,
        project_id=data.project_id,
        description=data.description,
        runner_id=data.runner_id,
        status=ConversationStatus.CREATING,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    background_tasks.add_task(init_conversation, conv.id)
    return _conv_to_dict(conv)


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, db: AsyncSession = Depends(get_db)):
    conv = await get_conversation_or_404(db, conv_id)
    await db.delete(conv)
    await db.commit()
    delete_conversation_dir(conv_id)
    return {"ok": True}


# ── Init sessions ──


@router.get("/{conv_id}/init/sessions")
async def get_init_sessions(conv_id: str, db: AsyncSession = Depends(get_db)):
    """Return init subtask sessions for frontend progress display."""
    await get_conversation_or_404(db, conv_id)
    session_ids = [
        conversation_init_fetch(conv_id),
        conversation_init_skills(conv_id),
    ]
    result = await db.execute(
        select(Session).where(Session.session_id.in_(session_ids))
    )
    sessions = result.scalars().all()
    return [
        {
            "session_id": s.session_id,
            "type": s.type,
            "status": s.status,
            "error": s.error,
        }
        for s in sessions
    ]


@router.post("/{conv_id}/retry-init")
async def retry_init(
    conv_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    conv = await get_conversation_or_404(db, conv_id)
    if conv.status not in (ConversationStatus.FAILED, ConversationStatus.CREATING):
        return {"ok": False, "detail": "Conversation is not in a retryable state"}
    conv.status = ConversationStatus.CREATING
    await db.commit()
    background_tasks.add_task(init_conversation, conv.id)
    return {"ok": True}
