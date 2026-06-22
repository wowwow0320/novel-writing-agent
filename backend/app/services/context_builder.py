import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import Episode, Story, StoryBibleEntry
from app.services.episode_text import full_episode_writing_text
from app.services.graph_sync import graph_context_text


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


def _bible_pin_top(entries: list[StoryBibleEntry], top_n: int = 8) -> list[StoryBibleEntry]:
    """importance >= 4 인 바이블 항목만 추려 상위 top_n개 반환. importance 없는 항목은 3으로 간주하고 제외."""

    def _imp(e: StoryBibleEntry) -> int:
        try:
            meta = e.extra if isinstance(e.extra, dict) else {}
            return int(meta.get("importance", 3) or 3)
        except (TypeError, ValueError):
            return 3

    ranked = sorted(
        [e for e in entries if _imp(e) >= 4],
        key=lambda e: (-_imp(e), e.name or ""),
    )
    return ranked[:top_n]


def format_global_context_pin(
    ctx_like: dict[str, Any],
    bible_top: list[StoryBibleEntry] | None = None,
) -> str:
    """시스템 프롬프트 최상단에 박을 Global Context Pin 블록을 만든다.

    - `00_MASTER_PLAN.md §3` 규약의 고정 포맷.
    - ctx_like 는 build_writer_context() 반환 dict 또는 동일한 키 서브셋.
    - bible_top 이 주어지면 importance>=4 상위 항목을 포함.
    """
    title = str(ctx_like.get("title") or "").strip() or "(제목 없음)"
    genre = str(ctx_like.get("genre") or "").strip() or "미정"
    world = (ctx_like.get("world_setting") or "").strip()
    rules = ctx_like.get("global_rules")
    style_guide = (ctx_like.get("style_guide") or "").strip() or "(작가 기본 문체)"
    language = str(ctx_like.get("language") or "KO").upper()

    rules_line = "(없음)"
    if isinstance(rules, dict) and rules:
        try:
            rules_line = json.dumps(rules, ensure_ascii=False)
        except (TypeError, ValueError):
            rules_line = "(직렬화 불가)"

    bible_lines: list[str] = []
    if bible_top:
        for e in bible_top:
            desc = (e.description or "").strip().replace("\n", " ")
            if len(desc) > 140:
                desc = desc[:140] + "…"
            bible_lines.append(f"  · [{e.category.value}] {e.name}: {desc}")
    bible_block = "\n".join(bible_lines) if bible_lines else "  · (핵심 설정 없음)"

    return (
        "[Global Context Pin]\n"
        f"- 작품: {title} ({genre})\n"
        f"- 대전제(world_setting): {world or '(없음)'}\n"
        f"- 전역 규칙(global_rules JSON): {rules_line}\n"
        "- 핵심 설정(바이블 요약, importance>=4):\n"
        f"{bible_block}\n"
        f"- 언어: {language}\n"
        f"- 문체 지침: {style_guide}\n"
        "이 섹션은 작품의 장기 제약입니다. 현재 챕터에서 무엇이 실제로 일어나는지는 작가 메모가 결정합니다.\n"
        "대전제와 바이블을 현재 장면의 기승전결 완결 지시로 해석하지 말고, 메모에 없는 사건을 만들기 위한 근거로 쓰지 마세요."
    )


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
    graph_ctx = ""
    if get_settings().graph_enabled:
        try:
            graph_ctx = await graph_context_text(story_id, limit=20)
        except Exception:
            graph_ctx = ""
    base: dict[str, Any] = {
        "title": story.title or "",
        "synopsis": story.synopsis or "",
        "world_setting": (story.world_setting or "").strip(),
        "global_rules": story.global_rules,
        "genre": story.genre or "",
        "style_guide": story.style_guide or "",
        "language": story.language or "KO",
        "bible_block": format_bible(bible),
        "graph_block": graph_ctx,
        "prev_summary": prev_sum,
        "sliding": sw,
    }
    base["pin"] = format_global_context_pin(base, bible_top=_bible_pin_top(bible))
    return base
