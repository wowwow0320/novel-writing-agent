import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Story
from app.schemas import StoryCreate, StoryOut, StoryUpdate
from app.services.foundation_memory import sync_foundation_memory

router = APIRouter(prefix="/stories", tags=["stories"])
logger = logging.getLogger(__name__)


@router.post("", response_model=StoryOut)
async def create_story(body: StoryCreate, db: AsyncSession = Depends(get_db)) -> Story:
    s = Story(
        title=body.title,
        genre=body.genre,
        synopsis=body.synopsis,
        world_setting=body.world_setting,
        global_rules=body.global_rules,
        style_guide=body.style_guide,
        language=body.language,
    )
    db.add(s)
    await db.flush()
    if (body.world_setting or "").strip():
        result = await sync_foundation_memory(db, s.id, body.world_setting or "", origin="story_create")
        if result.get("error"):
            logger.warning("배경 설정(world_setting) foundation sync 실패: %s", result.get("error"))
    await db.commit()
    await db.refresh(s)
    return s


@router.get("", response_model=list[StoryOut])
async def list_stories(db: AsyncSession = Depends(get_db)) -> list[Story]:
    r = await db.execute(select(Story).order_by(Story.created_at.desc()))
    return list(r.scalars().all())


@router.get("/{story_id}", response_model=StoryOut)
async def get_story(story_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Story:
    s = await db.get(Story, story_id)
    if not s:
        raise HTTPException(404, "story not found")
    return s


@router.patch("/{story_id}", response_model=StoryOut)
async def update_story(
    story_id: uuid.UUID,
    body: StoryUpdate,
    db: AsyncSession = Depends(get_db),
) -> Story:
    s = await db.get(Story, story_id)
    if not s:
        raise HTTPException(404, "story not found")
    values = body.model_dump(exclude_unset=True)
    for k, v in values.items():
        setattr(s, k, v)
    await db.flush()
    if "world_setting" in values and (s.world_setting or "").strip():
        result = await sync_foundation_memory(db, s.id, s.world_setting or "", origin="story_patch")
        if result.get("error"):
            logger.warning("배경 설정(world_setting) foundation sync 실패(update): %s", result.get("error"))
    await db.commit()
    await db.refresh(s)
    return s


@router.delete("/{story_id}")
async def delete_story(story_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    s = await db.get(Story, story_id)
    if not s:
        raise HTTPException(404, "story not found")
    await db.delete(s)
    await db.commit()
    return {"ok": "true"}
