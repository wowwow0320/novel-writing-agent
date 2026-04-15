import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Story
from app.schemas import StoryCreate, StoryOut, StoryUpdate

router = APIRouter(prefix="/stories", tags=["stories"])


@router.post("", response_model=StoryOut)
async def create_story(body: StoryCreate, db: AsyncSession = Depends(get_db)) -> Story:
    s = Story(
        title=body.title,
        genre=body.genre,
        synopsis=body.synopsis,
        style_guide=body.style_guide,
        language=body.language,
    )
    db.add(s)
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
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
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
