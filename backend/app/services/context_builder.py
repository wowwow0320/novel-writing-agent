import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import Episode, Story, StoryBibleEntry
from app.services.episode_text import full_episode_writing_text


async def load_story_episodes(session: AsyncSession, story_id: uuid.UUID) -> tuple[Story, list[Episode]]:
    r = await session.execute(
        select(Story)
        .where(Story.id == story_id)
        .options(selectinload(Story.episodes).selectinload(Episode.bodies))
    )
    story = r.scalar_one_or_none()
    if not story:
        raise ValueError("story not found")
    eps = sorted(story.episodes, key=lambda e: e.chapter_num)
    return story, eps


def format_bible(entries: list[StoryBibleEntry], limit: int = 40) -> str:
    lines: list[str] = []
    for e in entries[:limit]:
        lines.append(f"- [{e.category.value}] {e.name}: {e.description or ''}")
    return "\n".join(lines)


async def fetch_bible(session: AsyncSession, story_id: uuid.UUID) -> list[StoryBibleEntry]:
    r = await session.execute(select(StoryBibleEntry).where(StoryBibleEntry.story_id == story_id))
    return list(r.scalars().all())


def sliding_window_context(
    episodes: list[Episode],
    current_chapter: int,
    recent_full: int | None = None,
) -> dict[str, Any]:
    s = get_settings()
    n = recent_full if recent_full is not None else s.rag_recent_full_episodes
    before = [e for e in episodes if e.chapter_num < current_chapter]
    older = before[:-n] if len(before) > n else []
    recent = before[-n:] if before else []

    older_summaries = "\n".join(
        f"챕터 {e.chapter_num} 요약: {e.summary or '(없음)'}" for e in older
    )
    recent_full_text = "\n\n---\n\n".join(
        f"[챕터 {e.chapter_num} 전문]\n{(full_episode_writing_text(e) or e.raw_memory or '').strip()}"
        for e in recent
    )
    return {
        "older_summaries": older_summaries,
        "recent_full": recent_full_text,
        "combined_for_prompt": (
            f"[이전 챕터들 요약]\n{older_summaries}\n\n[최근 {len(recent)}개 챕터 전문]\n{recent_full_text}".strip()
        ),
    }


def prev_chapter_summary(episodes: list[Episode], current_chapter: int) -> str:
    prev = [e for e in episodes if e.chapter_num == current_chapter - 1]
    if not prev:
        return ""
    return (prev[0].summary or "").strip()


async def build_writer_context(
    session: AsyncSession,
    story_id: uuid.UUID,
    chapter_num: int,
) -> dict[str, Any]:
    story, episodes = await load_story_episodes(session, story_id)
    bible = await fetch_bible(session, story_id)
    sw = sliding_window_context(episodes, chapter_num)
    prev_sum = prev_chapter_summary(episodes, chapter_num)
    return {
        "synopsis": story.synopsis or "",
        "genre": story.genre or "",
        "style_guide": story.style_guide or "",
        "language": story.language or "KO",
        "bible_block": format_bible(bible),
        "prev_summary": prev_sum,
        "sliding": sw,
    }
