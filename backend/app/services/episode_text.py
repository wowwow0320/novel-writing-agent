"""챕터(Episode)의 다중 본문(episode_bodies)을 하나의 문자열로 합친다."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BodySegmentLink, Episode, EpisodeBody


def combine_episode_bodies(bodies: Iterable[EpisodeBody]) -> str:
    """본문 블록을 순서대로 이어 붙인다. 이전 블록과의 연결 방식은 각 블록의 link_to_previous에 따른다."""
    sorted_b = sorted(bodies, key=lambda x: x.segment_index)
    parts: list[str] = []
    for i, b in enumerate(sorted_b):
        content = (b.content or "").strip()
        if i > 0:
            link = b.link_to_previous
            if link == BodySegmentLink.omnibus:
                parts.append("\n\n* * *\n\n")
            else:
                parts.append("\n\n")
        parts.append(content)
    return "".join(parts)


def full_episode_writing_text(ep: Episode) -> str:
    """RAG·요약·바이블 등에 쓰는 챕터 전체 본문(episode_bodies 합본)."""
    if ep.bodies:
        return combine_episode_bodies(ep.bodies).strip()
    return ""


async def replace_episode_bodies(
    session: AsyncSession,
    episode: Episode,
    items: list[tuple[str | None, str, BodySegmentLink | None]],
) -> None:
    """items: (title, content, link_to_previous) 순서가 segment_index가 된다. 첫 항목의 link는 무시되어 None으로 저장."""
    await session.execute(delete(EpisodeBody).where(EpisodeBody.episode_id == episode.id))
    for pos, (title, content, link) in enumerate(items):
        link_val = None if pos == 0 else (link or BodySegmentLink.continuous)
        row = EpisodeBody(
            id=uuid.uuid4(),
            story_id=episode.story_id,
            episode_id=episode.id,
            segment_index=pos,
            title=(title or None) if title else None,
            content=content or "",
            link_to_previous=link_val,
        )
        session.add(row)
    await session.flush()
