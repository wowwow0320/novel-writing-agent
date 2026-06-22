import logging
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import Episode, EpisodeBody, Story, StoryEntity, StoryEvent, StoryRelationship, StorySummaryNode
from app.services import llm
from app.services.episode_text import full_episode_writing_text

logger = logging.getLogger(__name__)

SUMMARY_LEVELS = {"foundation", "body_group", "chapter", "arc", "volume", "work"}
BODY_GROUP_SIZE = 4
ARC_CHAPTER_SIZE = 8
VOLUME_ARC_SIZE = 6
VOLUME_CHAPTER_SIZE = ARC_CHAPTER_SIZE * VOLUME_ARC_SIZE


@dataclass(slots=True)
class SummarySearchHit:
    id: str
    node_key: str
    level: str
    summary: str
    chapter_start: int | None = None
    chapter_end: int | None = None
    score: float | None = None
    parent_id: str | None = None
    ancestor_ids: list[str] | None = None


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


def _clip(value: str | None, limit: int) -> str:
    text_value = (value or "").strip()
    if len(text_value) <= limit:
        return text_value
    return text_value[: max(0, limit - 1)].rstrip() + "…"


def _tokenize(value: str | None) -> list[str]:
    return [x.lower() for x in re.findall(r"[a-zA-Z가-힣0-9]{2,}", value or "")]


def _token_overlap(query: str | None, summary: str | None) -> float:
    q = set(_tokenize(query))
    if not q:
        return 0.0
    s = set(_tokenize(summary))
    return len(q & s) / max(1, len(q))


def _token_count(value: str | None) -> int:
    tokens = _tokenize(value)
    if tokens:
        return len(tokens)
    return max(0, math.ceil(len(value or "") / 4))


def _keywords(value: str | None, limit: int = 16) -> list[str]:
    counts: dict[str, int] = {}
    for token in _tokenize(value):
        counts[token] = counts.get(token, 0) + 1
    return [
        token
        for token, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _json_id_list(values: Iterable[Any]) -> list[str] | None:
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        text_value = str(value)
        if text_value and text_value not in out:
            out.append(text_value)
    return out or None


def group_bodies_for_summary(
    bodies: list[Any],
    group_size: int = BODY_GROUP_SIZE,
) -> list[list[Any]]:
    size = max(3, min(5, int(group_size or BODY_GROUP_SIZE)))
    return [bodies[i : i + size] for i in range(0, len(bodies), size)]


def level_boost(level: str | None) -> float:
    return {
        "work": 0.060,
        "volume": 0.052,
        "arc": 0.044,
        "chapter": 0.030,
        "foundation": 0.028,
        "body_group": 0.015,
    }.get((level or "").strip().lower(), 0.0)


def summary_node_rank(row: dict[str, Any]) -> float:
    semantic = float(row.get("semantic_score") or row.get("score") or 0.0)
    entity_overlap = float(row.get("entity_overlap") or 0.0)
    event_overlap = float(row.get("event_overlap") or 0.0)
    relationship_overlap = float(row.get("relationship_overlap") or 0.0)
    chapter_proximity = float(row.get("chapter_proximity") or 0.0)
    stale_penalty = 0.18 if bool(row.get("stale")) else 0.0
    return round(
        semantic * 0.52
        + entity_overlap * 0.18
        + event_overlap * 0.12
        + relationship_overlap * 0.08
        + level_boost(str(row.get("level") or ""))
        + chapter_proximity * 0.04
        - stale_penalty,
        6,
    )


def choose_summary_hits(rows: list[dict[str, Any]], query: str = "", limit: int = 8) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["coverage"] = float(item.get("coverage") or _token_overlap(query, str(item.get("summary") or "")))
        item["rank"] = summary_node_rank(item)
        if (
            str(item.get("level") or "") in {"foundation", "arc", "volume", "work"}
            and float(item.get("semantic_score") or item.get("score") or 0.0) >= 0.78
            and item["coverage"] >= 0.30
        ):
            item["rank"] += 0.04
        enriched.append(item)
    enriched.sort(
        key=lambda item: (
            -float(item.get("rank") or 0.0),
            -level_boost(str(item.get("level") or "")),
            str(item.get("node_key") or item.get("id") or ""),
        )
    )
    return enriched[:limit]


async def embed_summary_nodes(session: AsyncSession, rows: list[StorySummaryNode]) -> int:
    if not rows or get_settings().embedding_provider == "none":
        return 0
    targets = [row for row in rows if (row.summary or "").strip()]
    if not targets:
        return 0
    try:
        embeddings = await llm.embed_texts([f"[{row.level}] {row.summary}".strip() for row in targets])
    except Exception as exc:
        logger.warning("story_summary_nodes 임베딩 실패: %s", exc)
        return 0
    count = 0
    for row, vec in zip(targets, embeddings):
        if vec:
            row.embedding = vec
            count += 1
    await session.flush()
    return count


async def upsert_summary_node(
    session: AsyncSession,
    *,
    story_id: uuid.UUID,
    node_key: str,
    level: str,
    summary: str,
    episode_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    root_id: uuid.UUID | None = None,
    depth: int = 0,
    path: list[str] | None = None,
    ordinal: int | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    source_body_ids: list[str] | None = None,
    source_episode_ids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    event_ids: list[str] | None = None,
    relationship_ids: list[str] | None = None,
    keywords: list[str] | None = None,
    coverage_score: float | None = None,
    stale: bool = False,
    metadata: dict[str, Any] | None = None,
) -> StorySummaryNode:
    if level not in SUMMARY_LEVELS:
        raise ValueError(f"unsupported summary node level: {level}")
    r = await session.execute(
        select(StorySummaryNode)
        .where(StorySummaryNode.story_id == story_id)
        .where(StorySummaryNode.node_key == node_key)
    )
    row = r.scalar_one_or_none()
    if row is None:
        row = StorySummaryNode(story_id=story_id, node_key=node_key, level=level)
        session.add(row)
    row.episode_id = episode_id
    row.parent_id = parent_id
    row.root_id = root_id
    row.depth = depth
    row.path = path or [node_key]
    row.ordinal = ordinal
    row.chapter_start = chapter_start
    row.chapter_end = chapter_end
    row.source_body_ids = source_body_ids
    row.source_episode_ids = source_episode_ids
    row.entity_ids = entity_ids
    row.event_ids = event_ids
    row.relationship_ids = relationship_ids
    row.summary = summary.strip()
    row.keywords = keywords or _keywords(summary)
    row.token_count = _token_count(summary)
    row.coverage_score = coverage_score
    row.stale = stale
    row.extra = metadata
    await session.flush()
    if row.root_id is None and level in {"foundation", "work"}:
        row.root_id = row.id
        await session.flush()
    return row


async def mark_summary_tree_stale(
    session: AsyncSession,
    story_id: uuid.UUID,
    *,
    episode_id: uuid.UUID | None = None,
    chapter_num: int | None = None,
) -> int:
    stmt = select(StorySummaryNode).where(StorySummaryNode.story_id == story_id)
    if episode_id is not None:
        stmt = stmt.where(
            or_(
                StorySummaryNode.episode_id == episode_id,
                StorySummaryNode.level.in_(["arc", "volume", "work"]),
            )
        )
    elif chapter_num is not None:
        stmt = stmt.where(
            or_(
                (
                    (StorySummaryNode.chapter_start <= chapter_num)
                    & (StorySummaryNode.chapter_end >= chapter_num)
                ),
                StorySummaryNode.level.in_(["work"]),
            )
        )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.stale = True
    await session.flush()
    return len(rows)


async def _entity_event_relationship_ids(
    session: AsyncSession,
    story_id: uuid.UUID,
    *,
    chapter_start: int | None,
    chapter_end: int | None,
) -> tuple[list[str] | None, list[str] | None, list[str] | None]:
    ent_stmt = select(StoryEntity).where(StoryEntity.story_id == story_id).order_by(StoryEntity.importance.desc()).limit(80)
    if chapter_start is not None and chapter_end is not None:
        ent_stmt = ent_stmt.where(
            or_(
                StoryEntity.first_chapter_num.is_(None),
                StoryEntity.first_chapter_num <= chapter_end,
            )
        )
    entities = list((await session.execute(ent_stmt)).scalars().all())

    ev_stmt = select(StoryEvent).where(StoryEvent.story_id == story_id).order_by(StoryEvent.chapter_num, StoryEvent.event_order)
    if chapter_start is not None and chapter_end is not None:
        ev_stmt = ev_stmt.where(
            or_(
                StoryEvent.chapter_num.is_(None),
                StoryEvent.chapter_num.between(chapter_start, chapter_end),
            )
        )
    events = list((await session.execute(ev_stmt.limit(120))).scalars().all())

    rel_stmt = select(StoryRelationship).where(StoryRelationship.story_id == story_id).order_by(StoryRelationship.confidence.desc()).limit(120)
    relationships = list((await session.execute(rel_stmt)).scalars().all())
    return (
        _json_id_list(row.id for row in entities),
        _json_id_list(row.id for row in events),
        _json_id_list(row.id for row in relationships),
    )


async def _build_rollup_summary(
    label: str,
    source_summaries: list[str],
    max_chars: int,
) -> str:
    source = "\n".join(f"- {s.strip()}" for s in source_summaries if s and s.strip())
    if not source.strip():
        return ""
    if len(source) <= max_chars:
        return source[:max_chars]
    try:
        raw = await llm.complete_chat(
            "당신은 장편 소설의 기억 트리를 압축하는 편집자입니다. 사건 순서와 인과, 인물 관계를 보존해 요약하세요.",
            f"{label} 요약을 {max_chars}자 이내로 작성하세요.\n\n{source}",
            temperature=0.2,
        )
        return _clip(raw, max_chars)
    except Exception as exc:
        logger.warning("summary_tree rollup LLM 실패(%s): %s", label, exc)
        return _clip(source, max_chars)


async def rebuild_episode_summary_tree(
    session: AsyncSession,
    story_id: uuid.UUID,
    episode_id: uuid.UUID,
    *,
    group_size: int = BODY_GROUP_SIZE,
    rebuild_rollups: bool = True,
) -> dict[str, Any]:
    r = await session.execute(
        select(Episode).where(Episode.id == episode_id).options(selectinload(Episode.bodies))
    )
    episode = r.scalar_one_or_none()
    if episode is None:
        raise ValueError("episode not found")
    bodies = sorted(episode.bodies or [], key=lambda row: row.segment_index)
    await session.execute(
        delete(StorySummaryNode)
        .where(StorySummaryNode.story_id == story_id)
        .where(StorySummaryNode.episode_id == episode_id)
        .where(StorySummaryNode.level.in_(["body_group", "chapter"]))
    )
    await session.flush()

    changed: list[StorySummaryNode] = []
    body_group_nodes: list[StorySummaryNode] = []
    for idx, group in enumerate(group_bodies_for_summary(bodies, group_size=group_size)):
        group_summary = "\n".join(
            (body.body_summary or body.content[:500] or "").strip()
            for body in group
            if (body.body_summary or body.content or "").strip()
        )
        node = await upsert_summary_node(
            session,
            story_id=story_id,
            episode_id=episode.id,
            node_key=f"body_group:{episode.id}:{idx}",
            level="body_group",
            summary=_clip(group_summary, 1800),
            ordinal=idx,
            chapter_start=episode.chapter_num,
            chapter_end=episode.chapter_num,
            source_body_ids=_json_id_list(body.id for body in group),
            source_episode_ids=[str(episode.id)],
            coverage_score=min(1.0, len(group) / max(1, group_size)),
            stale=False,
            metadata={"group_size": len(group)},
        )
        changed.append(node)
        body_group_nodes.append(node)

    chapter_summary = episode.summary or _clip(full_episode_writing_text(episode), 2000)
    ent_ids, ev_ids, rel_ids = await _entity_event_relationship_ids(
        session,
        story_id,
        chapter_start=episode.chapter_num,
        chapter_end=episode.chapter_num,
    )
    chapter_node = await upsert_summary_node(
        session,
        story_id=story_id,
        episode_id=episode.id,
        node_key=f"chapter:{episode.chapter_num}",
        level="chapter",
        summary=chapter_summary,
        depth=1,
        chapter_start=episode.chapter_num,
        chapter_end=episode.chapter_num,
        source_body_ids=_json_id_list(body.id for body in bodies),
        source_episode_ids=[str(episode.id)],
        entity_ids=ent_ids,
        event_ids=ev_ids,
        relationship_ids=rel_ids,
        coverage_score=1.0,
        stale=False,
    )
    changed.append(chapter_node)
    for node in body_group_nodes:
        node.parent_id = chapter_node.id
        node.root_id = chapter_node.id
        node.depth = 2
        node.path = [chapter_node.node_key, node.node_key]
    await session.flush()

    rollup = await rebuild_story_rollup_nodes(session, story_id) if rebuild_rollups else {"nodes": [], "node_count": 0, "stale_cleared": 0, "arc_nodes": 0, "volume_nodes": 0, "work_nodes": 0}
    embedded = await embed_summary_nodes(session, changed + rollup.get("nodes", []))
    return {
        "nodes": len(changed) + rollup.get("node_count", 0),
        "stale_cleared": len(changed) + rollup.get("stale_cleared", 0),
        "embedded": embedded,
        "body_groups": len(body_group_nodes),
        "arc_nodes": rollup.get("arc_nodes", 0),
        "volume_nodes": rollup.get("volume_nodes", 0),
        "work_nodes": rollup.get("work_nodes", 0),
    }


async def rebuild_story_rollup_nodes(session: AsyncSession, story_id: uuid.UUID) -> dict[str, Any]:
    r_story = await session.execute(select(Story).where(Story.id == story_id))
    story = r_story.scalar_one_or_none()
    if story is None:
        return {"nodes": [], "node_count": 0, "stale_cleared": 0, "arc_nodes": 0, "volume_nodes": 0, "work_nodes": 0}

    chapter_nodes = list(
        (
            await session.execute(
                select(StorySummaryNode)
                .where(StorySummaryNode.story_id == story_id)
                .where(StorySummaryNode.level == "chapter")
                .order_by(StorySummaryNode.chapter_start)
            )
        )
        .scalars()
        .all()
    )
    changed: list[StorySummaryNode] = []
    arc_nodes: list[StorySummaryNode] = []
    for start in range(1, max([n.chapter_start or 0 for n in chapter_nodes] or [0]) + 1, ARC_CHAPTER_SIZE):
        end = start + ARC_CHAPTER_SIZE - 1
        members = [n for n in chapter_nodes if n.chapter_start and start <= n.chapter_start <= end]
        if not members:
            continue
        summary = await _build_rollup_summary(
            f"{start}-{end}화 arc",
            [n.summary for n in members],
            1800,
        )
        ent_ids, ev_ids, rel_ids = await _entity_event_relationship_ids(
            session,
            story_id,
            chapter_start=start,
            chapter_end=end,
        )
        node = await upsert_summary_node(
            session,
            story_id=story_id,
            node_key=f"arc:{start}-{end}",
            level="arc",
            summary=summary,
            depth=1,
            ordinal=(start - 1) // ARC_CHAPTER_SIZE,
            chapter_start=start,
            chapter_end=end,
            source_episode_ids=_json_id_list(
                eid
                for member in members
                for eid in (member.source_episode_ids or [])
            ),
            entity_ids=ent_ids,
            event_ids=ev_ids,
            relationship_ids=rel_ids,
            coverage_score=len(members) / ARC_CHAPTER_SIZE,
            stale=False,
        )
        for member in members:
            member.parent_id = node.id
            member.root_id = node.id
            member.path = [node.node_key, member.node_key]
        changed.append(node)
        arc_nodes.append(node)

    volume_nodes: list[StorySummaryNode] = []
    max_chapter = max([n.chapter_end or 0 for n in arc_nodes] or [0])
    for start in range(1, max_chapter + 1, VOLUME_CHAPTER_SIZE):
        end = start + VOLUME_CHAPTER_SIZE - 1
        members = [n for n in arc_nodes if n.chapter_start and start <= n.chapter_start <= end]
        if not members:
            continue
        summary = await _build_rollup_summary(
            f"{start}-{end}화 volume",
            [n.summary for n in members],
            2200,
        )
        node = await upsert_summary_node(
            session,
            story_id=story_id,
            node_key=f"volume:{start}-{end}",
            level="volume",
            summary=summary,
            depth=1,
            ordinal=(start - 1) // VOLUME_CHAPTER_SIZE,
            chapter_start=start,
            chapter_end=end,
            source_episode_ids=_json_id_list(
                eid
                for member in members
                for eid in (member.source_episode_ids or [])
            ),
            coverage_score=len(members) / VOLUME_ARC_SIZE,
            stale=False,
        )
        for member in members:
            member.parent_id = node.id
            member.root_id = node.id
            member.path = [node.node_key, member.node_key]
        changed.append(node)
        volume_nodes.append(node)

    foundation = list(
        (
            await session.execute(
                select(StorySummaryNode)
                .where(StorySummaryNode.story_id == story_id)
                .where(StorySummaryNode.level == "foundation")
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    work_sources = [n.summary for n in (foundation + volume_nodes + arc_nodes if not volume_nodes else foundation + volume_nodes)]
    if not work_sources and story.work_summary:
        work_sources = [story.work_summary]
    if work_sources:
        summary = await _build_rollup_summary("작품 전체", work_sources, get_settings().work_summary_max_chars)
        work_node = await upsert_summary_node(
            session,
            story_id=story_id,
            node_key="work",
            level="work",
            summary=summary,
            depth=0,
            chapter_start=1 if chapter_nodes else None,
            chapter_end=max_chapter or None,
            source_episode_ids=_json_id_list(
                eid
                for member in chapter_nodes
                for eid in (member.source_episode_ids or [])
            ),
            coverage_score=1.0 if chapter_nodes else None,
            stale=False,
        )
        for member in volume_nodes or arc_nodes:
            member.parent_id = work_node.id
            member.root_id = work_node.id
            member.path = [work_node.node_key, member.node_key]
        changed.append(work_node)
    await session.flush()
    return {
        "nodes": changed,
        "node_count": len(changed),
        "stale_cleared": len(changed),
        "arc_nodes": len(arc_nodes),
        "volume_nodes": len(volume_nodes),
        "work_nodes": 1 if any(n.level == "work" for n in changed) else 0,
    }


async def rebuild_story_summary_tree(session: AsyncSession, story_id: uuid.UUID) -> dict[str, Any]:
    episodes = list(
        (
            await session.execute(
                select(Episode)
                .where(Episode.story_id == story_id)
                .order_by(Episode.chapter_num)
                .options(selectinload(Episode.bodies))
            )
        )
        .scalars()
        .all()
    )
    total = {"nodes": 0, "stale_cleared": 0, "embedded": 0, "episodes": len(episodes)}
    for episode in episodes:
        if not (episode.summary or full_episode_writing_text(episode).strip()):
            continue
        result = await rebuild_episode_summary_tree(session, story_id, episode.id, rebuild_rollups=False)
        total["nodes"] += int(result.get("nodes", 0))
        total["stale_cleared"] += int(result.get("stale_cleared", 0))
        total["embedded"] += int(result.get("embedded", 0))
    rollup = await rebuild_story_rollup_nodes(session, story_id)
    total["nodes"] += int(rollup.get("node_count", 0))
    total["stale_cleared"] += int(rollup.get("stale_cleared", 0))
    total["embedded"] += await embed_summary_nodes(session, rollup.get("nodes", []))
    return total


async def _summary_ancestors(session: AsyncSession, row: StorySummaryNode) -> list[str]:
    out: list[str] = []
    current = row
    seen: set[uuid.UUID] = set()
    while current.parent_id and current.parent_id not in seen:
        seen.add(current.parent_id)
        parent = await session.get(StorySummaryNode, current.parent_id)
        if parent is None:
            break
        out.append(str(parent.id))
        current = parent
    return out


def _chapter_proximity(row: StorySummaryNode, chapter_num: int | None) -> float:
    if chapter_num is None or row.chapter_start is None:
        return 0.0
    start = row.chapter_start
    end = row.chapter_end or start
    if start <= chapter_num <= end:
        return 1.0
    distance = min(abs(chapter_num - start), abs(chapter_num - end))
    return max(0.0, 1.0 - (distance / 24.0))


async def _search_summary_nodes_vector(
    session: AsyncSession,
    story_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[tuple[StorySummaryNode, float]]:
    if get_settings().embedding_provider == "none":
        return []
    q_emb = await llm.embed_texts([query])
    if not q_emb or not q_emb[0]:
        return []
    stmt = text(
        """
        SELECT id, 1 - (embedding <=> (:q)::vector) AS score
        FROM story_summary_nodes
        WHERE story_id = CAST(:sid AS uuid) AND embedding IS NOT NULL
        ORDER BY embedding::halfvec(3072) <=> ((:q)::vector)::halfvec(3072)
        LIMIT :lim
        """
    )
    r = await session.execute(stmt, {"sid": str(story_id), "q": _vector_literal(q_emb[0]), "lim": limit})
    out: list[tuple[StorySummaryNode, float]] = []
    for row_id, score in r.fetchall():
        node = await session.get(StorySummaryNode, row_id)
        if node is not None:
            out.append((node, float(score or 0.0)))
    return out


async def _search_summary_nodes_trgm(
    session: AsyncSession,
    story_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[tuple[StorySummaryNode, float]]:
    stmt = text(
        """
        SELECT id,
               GREATEST(
                 similarity(summary, CAST(:q AS text)),
                 word_similarity(CAST(:q AS text), summary)
               ) AS sim
        FROM story_summary_nodes
        WHERE story_id = CAST(:sid AS uuid)
          AND (
            summary ILIKE CAST(:pat AS text)
            OR node_key ILIKE CAST(:pat AS text)
            OR similarity(summary, CAST(:q AS text)) > 0.10
            OR word_similarity(CAST(:q AS text), summary) > 0.30
          )
        ORDER BY sim DESC NULLS LAST
        LIMIT :lim
        """
    )
    r = await session.execute(stmt, {"sid": str(story_id), "q": query, "pat": f"%{query}%", "lim": limit})
    out: list[tuple[StorySummaryNode, float]] = []
    for row_id, score in r.fetchall():
        node = await session.get(StorySummaryNode, row_id)
        if node is not None:
            out.append((node, float(score or 0.0)))
    return out


async def search_summary_nodes(
    session: AsyncSession,
    story_id: uuid.UUID,
    query: str,
    *,
    chapter_num: int | None = None,
    limit: int = 8,
) -> list[SummarySearchHit]:
    q = (query or "").strip()
    if not q:
        return []
    rows: list[tuple[StorySummaryNode, float]] = []
    try:
        rows = await _search_summary_nodes_vector(session, story_id, q, limit * 2)
    except Exception as exc:
        logger.warning("summary node vector 검색 실패: %s", exc)
        await session.rollback()
    if not rows:
        try:
            rows = await _search_summary_nodes_trgm(session, story_id, q, limit * 2)
        except Exception as exc:
            logger.warning("summary node trgm 검색 실패: %s", exc)
            await session.rollback()
            return []

    row_by_id: dict[str, tuple[StorySummaryNode, float]] = {str(node.id): (node, score) for node, score in rows}
    for node, score in list(rows):
        ancestor = node
        seen: set[uuid.UUID] = set()
        while ancestor.parent_id and ancestor.parent_id not in seen:
            seen.add(ancestor.parent_id)
            parent = await session.get(StorySummaryNode, ancestor.parent_id)
            if parent is None:
                break
            inherited = max(score - 0.04, 0.0)
            row_by_id.setdefault(str(parent.id), (parent, inherited))
            ancestor = parent

    candidates: list[dict[str, Any]] = []
    for node, score in row_by_id.values():
        candidates.append(
            {
                "id": str(node.id),
                "node_key": node.node_key,
                "level": node.level,
                "summary": node.summary,
                "semantic_score": score,
                "entity_overlap": _token_overlap(q, " ".join(node.keywords or []) + " " + node.summary),
                "event_overlap": 0.2 if node.event_ids else 0.0,
                "relationship_overlap": 0.2 if node.relationship_ids else 0.0,
                "chapter_proximity": _chapter_proximity(node, chapter_num),
                "stale": node.stale,
                "chapter_start": node.chapter_start,
                "chapter_end": node.chapter_end,
                "parent_id": str(node.parent_id) if node.parent_id else None,
                "ancestor_ids": await _summary_ancestors(session, node),
            }
        )
    chosen = choose_summary_hits(candidates, query=q, limit=limit)
    return [
        SummarySearchHit(
            id=str(row["id"]),
            node_key=str(row.get("node_key") or ""),
            level=str(row.get("level") or ""),
            summary=str(row.get("summary") or ""),
            chapter_start=row.get("chapter_start"),
            chapter_end=row.get("chapter_end"),
            score=float(row.get("rank") or row.get("semantic_score") or 0.0),
            parent_id=row.get("parent_id"),
            ancestor_ids=list(row.get("ancestor_ids") or []),
        )
        for row in chosen
    ]
