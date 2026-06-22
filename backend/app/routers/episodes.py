import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Episode, Story
from app.schemas import EpisodeCreate, EpisodeOut, EpisodeUpdate, ReplaceEpisodeBodiesRequest
from app.services.episode_text import replace_episode_bodies
from app.services.summary_tree import mark_summary_tree_stale

router = APIRouter(prefix="/stories/{story_id}/episodes", tags=["episodes"])


async def _load_episode(
    db: AsyncSession,
    story_id: uuid.UUID,
    episode_id: uuid.UUID,
) -> Episode | None:
    r = await db.execute(
        select(Episode)
        .where(Episode.id == episode_id, Episode.story_id == story_id)
        .options(selectinload(Episode.bodies))
    )
    return r.scalar_one_or_none()


@router.post("", response_model=EpisodeOut)
async def create_episode(
    story_id: uuid.UUID,
    body: EpisodeCreate,
    db: AsyncSession = Depends(get_db),
) -> Episode:
    st = await db.get(Story, story_id)
    if not st:
        raise HTTPException(404, "story not found")
    e = Episode(
        story_id=story_id,
        chapter_num=body.chapter_num,
        raw_memory=body.raw_memory,
        summary=body.summary,
        status=body.status,
    )
    db.add(e)
    await db.flush()
    first_text = body.ai_content if body.ai_content is not None else ""
    await replace_episode_bodies(db, e, [(None, first_text, None, None, None)])
    await db.commit()
    out = await _load_episode(db, story_id, e.id)
    assert out is not None
    return out


@router.get("", response_model=list[EpisodeOut])
async def list_episodes(story_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[Episode]:
    st = await db.get(Story, story_id)
    if not st:
        raise HTTPException(404, "story not found")
    r = await db.execute(
        select(Episode)
        .where(Episode.story_id == story_id)
        .options(selectinload(Episode.bodies))
        .order_by(Episode.chapter_num)
    )
    return list(r.scalars().all())


@router.get("/{episode_id}", response_model=EpisodeOut)
async def get_episode(
    story_id: uuid.UUID,
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Episode:
    e = await _load_episode(db, story_id, episode_id)
    if not e:
        raise HTTPException(404, "episode not found")
    return e


@router.put("/{episode_id}/bodies", response_model=EpisodeOut)
async def replace_bodies(
    story_id: uuid.UUID,
    episode_id: uuid.UUID,
    body: ReplaceEpisodeBodiesRequest,
    db: AsyncSession = Depends(get_db),
) -> Episode:
    if not body.bodies:
        raise HTTPException(400, "bodies는 최소 1개 필요합니다")
    e = await _load_episode(db, story_id, episode_id)
    if not e:
        raise HTTPException(404, "episode not found")
    tuples = [
        (b.title, b.content, b.link_to_previous, b.body_summary, b.meta_tags) for b in body.bodies
    ]
    await replace_episode_bodies(db, e, tuples)
    await mark_summary_tree_stale(db, story_id, episode_id=episode_id, chapter_num=e.chapter_num)
    await db.commit()
    out = await _load_episode(db, story_id, episode_id)
    assert out is not None
    return out


@router.patch("/{episode_id}", response_model=EpisodeOut)
async def update_episode(
    story_id: uuid.UUID,
    episode_id: uuid.UUID,
    body: EpisodeUpdate,
    db: AsyncSession = Depends(get_db),
) -> Episode:
    e = await _load_episode(db, story_id, episode_id)
    if not e:
        raise HTTPException(404, "episode not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(e, k, v)
    if {"raw_memory", "summary", "chapter_events", "meta_tags"} & set(data.keys()):
        await mark_summary_tree_stale(db, story_id, episode_id=episode_id, chapter_num=e.chapter_num)
    await db.commit()
    out = await _load_episode(db, story_id, episode_id)
    assert out is not None
    return out


@router.delete("/{episode_id}")
async def delete_episode(
    story_id: uuid.UUID,
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    e = await db.get(Episode, episode_id)
    if not e or e.story_id != story_id:
        raise HTTPException(404, "episode not found")
    await db.delete(e)
    await db.commit()
    return {"ok": "true"}
