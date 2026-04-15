import logging
import uuid
from typing import Any, Literal

from sqlalchemy import Select, delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import Episode, EpisodeBody, EpisodeChunk, StoryBibleEntry
from app.services import llm
from app.services.episode_text import full_episode_writing_text

logger = logging.getLogger(__name__)


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


def bible_document_for_embed(row: StoryBibleEntry) -> str:
    """스토리 바이블 한 항목을 임베딩용 문서 한 덩어리로 만든다."""
    return f"[{row.category.value}] {row.name}\n{row.description or ''}".strip()


async def embed_bible_entries(session: AsyncSession, rows: list[StoryBibleEntry]) -> None:
    """바이블 행들에 대해 임베딩을 채운다 (provider가 none이면 embedding=NULL)."""
    settings = get_settings()
    if not rows:
        return
    if settings.embedding_provider == "none":
        for row in rows:
            row.embedding = None
        await session.flush()
        return
    texts: list[str] = []
    targets: list[StoryBibleEntry] = []
    for row in rows:
        t = bible_document_for_embed(row)
        if t:
            texts.append(t)
            targets.append(row)
        else:
            row.embedding = None
    if not texts:
        await session.flush()
        return
    embs = await llm.embed_texts(texts)
    for row, vec in zip(targets, embs):
        row.embedding = vec if vec else None
    await session.flush()


async def upsert_chunks_for_episode(
    session: AsyncSession,
    story_id: uuid.UUID,
    episode: Episode,
    chunk_size: int = 1200,
    overlap: int = 200,
) -> None:
    r = await session.execute(
        select(Episode).where(Episode.id == episode.id).options(selectinload(Episode.bodies))
    )
    ep = r.scalar_one()
    await session.execute(delete(EpisodeChunk).where(EpisodeChunk.episode_id == episode.id))
    body = full_episode_writing_text(ep).strip()
    if not body:
        return
    chunks: list[str] = []
    i = 0
    while i < len(body):
        chunks.append(body[i : i + chunk_size])
        i += max(chunk_size - overlap, 1)
    settings = get_settings()
    embeddings: list[list[float]] = []
    if settings.embedding_provider != "none":
        embeddings = await llm.embed_texts(chunks)
    for idx, c in enumerate(chunks):
        row = EpisodeChunk(
            story_id=story_id,
            episode_id=episode.id,
            chunk_index=idx,
            content=c,
        )
        if embeddings and idx < len(embeddings) and embeddings[idx]:
            row.embedding = embeddings[idx]
        session.add(row)
    await session.flush()


def _rag_sort_key(score: float | None) -> tuple[int, float]:
    if score is None:
        return (1, 0.0)
    return (0, -score)


async def _search_episode_chunks_vector(
    session: AsyncSession,
    story_id: uuid.UUID,
    q_lit: str,
    limit: int,
) -> list[tuple[EpisodeChunk, float | None]]:
    stmt = text(
        """
        SELECT ec.id, ec.episode_id, ec.content,
               1 - (ec.embedding <=> (:q)::vector) AS score
        FROM episode_chunks ec
        WHERE ec.story_id = CAST(:sid AS uuid) AND ec.embedding IS NOT NULL
        ORDER BY ec.embedding <=> (:q)::vector
        LIMIT :lim
        """
    )
    r = await session.execute(stmt, {"q": q_lit, "sid": str(story_id), "lim": limit})
    out: list[tuple[EpisodeChunk, float | None]] = []
    for row in r.fetchall():
        cid, _eid, _content, score = row
        ch = await session.get(EpisodeChunk, cid)
        if ch:
            out.append((ch, float(score) if score is not None else None))
    return out


async def _search_bible_vector(
    session: AsyncSession,
    story_id: uuid.UUID,
    q_lit: str,
    limit: int,
) -> list[tuple[StoryBibleEntry, float | None]]:
    stmt = text(
        """
        SELECT id, 1 - (embedding <=> (:q)::vector) AS score
        FROM story_bible
        WHERE story_id = CAST(:sid AS uuid) AND embedding IS NOT NULL
        ORDER BY embedding <=> (:q)::vector
        LIMIT :lim
        """
    )
    r = await session.execute(stmt, {"q": q_lit, "sid": str(story_id), "lim": limit})
    out: list[tuple[StoryBibleEntry, float | None]] = []
    for row in r.fetchall():
        bid, score = row
        ent = await session.get(StoryBibleEntry, bid)
        if ent:
            out.append((ent, float(score) if score is not None else None))
    return out


RAGMergedRow = tuple[
    Literal["episode", "bible"],
    EpisodeChunk | StoryBibleEntry | None,
    float | None,
    str,
    uuid.UUID | None,
    int,
]


async def _search_trgm_episode_chunks(
    session: AsyncSession,
    story_id: uuid.UUID,
    q: str,
    lim: int,
) -> list[tuple[EpisodeChunk, float]]:
    """pg_trgm 기반 유사도. 확장 미적용 시 빈 리스트."""
    if len(q.strip()) < 2:
        return []
    pat = f"%{q}%"
    stmt = text(
        """
        SELECT ec.id,
               GREATEST(
                 similarity(ec.content, CAST(:q AS text)),
                 word_similarity(CAST(:q AS text), ec.content)
               ) AS sim
        FROM episode_chunks ec
        WHERE ec.story_id = CAST(:sid AS uuid)
          AND (
            ec.content ILIKE CAST(:pat AS text)
            OR similarity(ec.content, CAST(:q AS text)) > 0.11
            OR word_similarity(CAST(:q AS text), ec.content) > 0.32
          )
        ORDER BY sim DESC NULLS LAST
        LIMIT :lim
        """
    )
    try:
        r = await session.execute(stmt, {"q": q, "sid": str(story_id), "pat": pat, "lim": lim})
    except Exception as e:
        logger.warning("pg_trgm episode_chunks 검색 실패(폴백 전 트랜잭션 복구): %s", e)
        await session.rollback()
        return []
    out: list[tuple[EpisodeChunk, float | None]] = []
    for row in r.fetchall():
        cid, sim = row
        ch = await session.get(EpisodeChunk, cid)
        if ch:
            out.append((ch, float(sim) if sim is not None else None))
    return out


async def _search_trgm_bible(
    session: AsyncSession,
    story_id: uuid.UUID,
    q: str,
    lim: int,
) -> list[tuple[StoryBibleEntry, float]]:
    if len(q.strip()) < 2:
        return []
    pat = f"%{q}%"
    stmt = text(
        """
        SELECT sb.id,
               GREATEST(
                 similarity(sb.name, CAST(:q AS text)),
                 similarity(COALESCE(sb.description, ''), CAST(:q AS text)),
                 word_similarity(CAST(:q AS text), sb.name),
                 word_similarity(CAST(:q AS text), COALESCE(sb.description, ''))
               ) AS sim
        FROM story_bible sb
        WHERE sb.story_id = CAST(:sid AS uuid)
          AND (
            sb.name ILIKE CAST(:pat AS text)
            OR COALESCE(sb.description, '') ILIKE CAST(:pat AS text)
            OR similarity(sb.name, CAST(:q AS text)) > 0.18
            OR similarity(COALESCE(sb.description, ''), CAST(:q AS text)) > 0.11
            OR word_similarity(CAST(:q AS text), sb.name) > 0.4
            OR word_similarity(CAST(:q AS text), COALESCE(sb.description, '')) > 0.32
          )
        ORDER BY sim DESC NULLS LAST
        LIMIT :lim
        """
    )
    try:
        r = await session.execute(stmt, {"q": q, "sid": str(story_id), "pat": pat, "lim": lim})
    except Exception as e:
        logger.warning("pg_trgm story_bible 검색 실패(폴백 전 트랜잭션 복구): %s", e)
        await session.rollback()
        return []
    out: list[tuple[StoryBibleEntry, float | None]] = []
    for row in r.fetchall():
        bid, sim = row
        ent = await session.get(StoryBibleEntry, bid)
        if ent:
            out.append((ent, float(sim) if sim is not None else None))
    return out


async def search_rag_merged(
    session: AsyncSession,
    story_id: uuid.UUID,
    query: str,
    limit: int = 8,
) -> list[RAGMergedRow]:
    """
    에피소드 청크 + 스토리 바이블을 검색해 점수 순으로 반환.
    1) 임베딩 사용 시 벡터 유사도
    2) pg_trgm 문자열 유사도(부분 일치·오타에 강함)
    3) ILIKE 부분 문자열
    반환: (source, 객체 또는 None, score, snippet, episode_id|None, chapter_num)
    """
    q = (query or "").strip()
    if not q:
        return []
    settings = get_settings()
    if settings.embedding_provider != "none":
        try:
            q_emb = await llm.embed_texts([q])
            if q_emb and q_emb[0]:
                vec = q_emb[0]
                q_lit = _vector_literal(vec)
                ep_hits = await _search_episode_chunks_vector(session, story_id, q_lit, limit)
                bi_hits = await _search_bible_vector(session, story_id, q_lit, limit)
                merged: list[RAGMergedRow] = []
                for ch, score in ep_hits:
                    ep = await session.get(Episode, ch.episode_id)
                    merged.append(
                        (
                            "episode",
                            ch,
                            score,
                            ch.content[:1200],
                            ch.episode_id,
                            ep.chapter_num if ep else 0,
                        )
                    )
                for ent, score in bi_hits:
                    snip = bible_document_for_embed(ent)[:1200]
                    merged.append(("bible", ent, score, snip, None, 0))
                merged.sort(key=lambda x: _rag_sort_key(x[2]))
                if merged:
                    return merged[:limit]
        except Exception as e:
            logger.warning("RAG 벡터 검색 경로 실패, 문자열 검색으로 이어감: %s", e)
            await session.rollback()

    trgm_ep = await _search_trgm_episode_chunks(session, story_id, q, limit)
    trgm_bi = await _search_trgm_bible(session, story_id, q, limit)
    if trgm_ep or trgm_bi:
        trgm_merged: list[RAGMergedRow] = []
        for ch, score in trgm_ep:
            ep = await session.get(Episode, ch.episode_id)
            trgm_merged.append(
                (
                    "episode",
                    ch,
                    score,
                    ch.content[:1200],
                    ch.episode_id,
                    ep.chapter_num if ep else 0,
                )
            )
        for ent, score in trgm_bi:
            snip = bible_document_for_embed(ent)[:1200]
            trgm_merged.append(("bible", ent, score, snip, None, 0))
        trgm_merged.sort(key=lambda x: _rag_sort_key(x[2]))
        return trgm_merged[:limit]

    pattern = f"%{q}%"
    stmt_e: Select[tuple[EpisodeChunk]] = (
        select(EpisodeChunk)
        .where(EpisodeChunk.story_id == story_id)
        .where(EpisodeChunk.content.ilike(pattern))
        .limit(limit)
    )
    r1 = await session.execute(stmt_e)
    chunks = list(r1.scalars().all())
    stmt_b = (
        select(StoryBibleEntry)
        .where(StoryBibleEntry.story_id == story_id)
        .where(
            (StoryBibleEntry.name.ilike(pattern)) | (StoryBibleEntry.description.ilike(pattern))
        )
        .limit(limit)
    )
    r2 = await session.execute(stmt_b)
    bible_rows = list(r2.scalars().all())
    kw: list[RAGMergedRow] = []
    for ch in chunks:
        ep = await session.get(Episode, ch.episode_id)
        kw.append(
            (
                "episode",
                ch,
                None,
                ch.content[:1200],
                ch.episode_id,
                ep.chapter_num if ep else 0,
            )
        )
    for ent in bible_rows:
        kw.append(
            (
                "bible",
                ent,
                None,
                bible_document_for_embed(ent)[:1200],
                None,
                0,
            )
        )
    return kw[:limit]


async def search_similar(
    session: AsyncSession,
    story_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[tuple[EpisodeChunk, float | None]]:
    """하위 호환: 에피소드 청크만 검색 (벡터 또는 키워드)."""
    rows = await search_rag_merged(session, story_id, query, limit)
    out: list[tuple[EpisodeChunk, float | None]] = []
    for src, obj, score, _snip, _eid, _ch in rows:
        if src == "episode" and isinstance(obj, EpisodeChunk):
            out.append((obj, score))
    return out


async def keyword_fallback_episodes(
    session: AsyncSession,
    story_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[tuple[Episode, str]]:
    pattern = f"%{query.strip()}%"
    stmt = (
        select(Episode)
        .outerjoin(EpisodeBody, EpisodeBody.episode_id == Episode.id)
        .where(Episode.story_id == story_id)
        .where(
            or_(
                Episode.summary.ilike(pattern),
                EpisodeBody.content.ilike(pattern),
            )
        )
        .distinct()
        .options(selectinload(Episode.bodies))
        .limit(limit)
    )
    r = await session.execute(stmt)
    eps = list(r.scalars().all())
    return [(e, full_episode_writing_text(e)[:800]) for e in eps]


async def keyword_fallback_bible(
    session: AsyncSession,
    story_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[tuple[StoryBibleEntry, str]]:
    pattern = f"%{query.strip()}%"
    stmt = (
        select(StoryBibleEntry)
        .where(StoryBibleEntry.story_id == story_id)
        .where(
            (StoryBibleEntry.name.ilike(pattern))
            | (StoryBibleEntry.description.ilike(pattern))
        )
        .limit(limit)
    )
    r = await session.execute(stmt)
    rows = list(r.scalars().all())
    return [(row, bible_document_for_embed(row)[:800]) for row in rows]
