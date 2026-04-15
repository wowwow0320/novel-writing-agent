import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Story, StoryBibleEntry
from app.services import rag
from app.schemas import BibleCreate, BibleOut, BibleUpdate

router = APIRouter(prefix="/stories/{story_id}/bible", tags=["story_bible"])


@router.post("", response_model=BibleOut)
async def create_entry(
    story_id: uuid.UUID,
    body: BibleCreate,
    db: AsyncSession = Depends(get_db),
) -> StoryBibleEntry:
    st = await db.get(Story, story_id)
    if not st:
        raise HTTPException(404, "story not found")
    row = StoryBibleEntry(
        story_id=story_id,
        category=body.category,
        name=body.name,
        description=body.description,
        extra=body.metadata,
    )
    db.add(row)
    await db.flush()
    await rag.embed_bible_entries(db, [row])
    await db.commit()
    await db.refresh(row)
    return row


@router.get("", response_model=list[BibleOut])
async def list_entries(story_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[StoryBibleEntry]:
    st = await db.get(Story, story_id)
    if not st:
        raise HTTPException(404, "story not found")
    r = await db.execute(select(StoryBibleEntry).where(StoryBibleEntry.story_id == story_id))
    return list(r.scalars().all())


@router.patch("/{entry_id}", response_model=BibleOut)
async def update_entry(
    story_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: BibleUpdate,
    db: AsyncSession = Depends(get_db),
) -> StoryBibleEntry:
    row = await db.get(StoryBibleEntry, entry_id)
    if not row or row.story_id != story_id:
        raise HTTPException(404, "entry not found")
    data = body.model_dump(exclude_unset=True)
    if "metadata" in data:
        row.extra = data.pop("metadata")
    for k, v in data.items():
        setattr(row, k, v)
    await db.flush()
    await rag.embed_bible_entries(db, [row])
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{entry_id}")
async def delete_entry(
    story_id: uuid.UUID,
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    row = await db.get(StoryBibleEntry, entry_id)
    if not row or row.story_id != story_id:
        raise HTTPException(404, "entry not found")
    await db.delete(row)
    await db.commit()
    return {"ok": "true"}
