import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import Text, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services import rag
from app.services.graph_sync import graph_context_text
from app.services.summary_tree import search_summary_nodes


def normalize_entity_name(value: str | None) -> str:
    """Canonical 비교용 이름. 한글은 공백만 정리하고, 영문은 소문자화한다."""
    text = (value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _clip(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


@dataclass(slots=True)
class MemoryEntityHit:
    id: str
    name: str
    entity_type: str
    description: str = ""
    importance: int = 3


@dataclass(slots=True)
class MemoryRelationshipHit:
    id: str
    source: str
    target: str
    relation_type: str
    current_state: str = ""
    evidence: str = ""
    confidence: float | None = None


@dataclass(slots=True)
class MemoryEventHit:
    id: str
    title: str
    summary: str = ""
    chapter_num: int | None = None
    importance: int = 3


@dataclass(slots=True)
class MemoryExcerptHit:
    source: str
    snippet: str
    chapter_num: int | None = None
    score: float | None = None
    episode_id: str | None = None
    segment_index: int | None = None
    paragraph_index: int | None = None


@dataclass(slots=True)
class MemorySummaryNodeHit:
    id: str
    node_key: str
    level: str
    summary: str
    chapter_start: int | None = None
    chapter_end: int | None = None
    score: float | None = None
    parent_id: str | None = None
    ancestor_ids: list[str] | None = None


@dataclass(slots=True)
class MemoryBundle:
    query: str
    entities: list[MemoryEntityHit] = field(default_factory=list)
    relationships: list[MemoryRelationshipHit] = field(default_factory=list)
    events: list[MemoryEventHit] = field(default_factory=list)
    excerpts: list[MemoryExcerptHit] = field(default_factory=list)
    summary_nodes: list[MemorySummaryNodeHit] = field(default_factory=list)
    graph_context: str = ""
    warnings: list[str] = field(default_factory=list)


def _dataclass_dict(row: Any) -> dict[str, Any]:
    data = asdict(row)
    for key, value in list(data.items()):
        if isinstance(value, uuid.UUID):
            data[key] = str(value)
    return data


def memory_trace_from_bundle(bundle: MemoryBundle) -> dict[str, Any]:
    return {
        "query": bundle.query,
        "entities": [_dataclass_dict(e) for e in bundle.entities[:8]],
        "relationships": [_dataclass_dict(r) for r in bundle.relationships[:8]],
        "events": [_dataclass_dict(e) for e in bundle.events[:8]],
        "summary_nodes": [
            {
                **_dataclass_dict(e),
                "summary": _clip(e.summary, 220),
            }
            for e in bundle.summary_nodes[:8]
        ],
        "excerpts": [
            {
                **_dataclass_dict(e),
                "snippet": _clip(e.snippet, 180),
            }
            for e in bundle.excerpts[:8]
        ],
        "graph_context": _clip(bundle.graph_context, 800),
        "warnings": [_clip(w, 240) for w in bundle.warnings[:8]],
    }


def format_memory_bundle_for_prompt(bundle: MemoryBundle) -> str:
    lines: list[str] = ["[자동 검색된 장기 기억]", f"- 검색 질의: {bundle.query or '(없음)'}"]
    if bundle.entities:
        lines.append("\n[관련 인물/설정]")
        for e in bundle.entities[:8]:
            desc = _clip(e.description, 180)
            lines.append(f"- [{e.entity_type}] {e.name} (중요도 {e.importance}): {desc or '(설명 없음)'}")
    if bundle.relationships:
        lines.append("\n[관련 관계]")
        for r in bundle.relationships[:8]:
            state = f", 상태: {r.current_state}" if r.current_state else ""
            conf = f", 신뢰도: {r.confidence:.2f}" if r.confidence is not None else ""
            ev = _clip(r.evidence, 180)
            lines.append(f"- {r.source} -[{r.relation_type}]-> {r.target}{state}{conf}: {ev}")
    if bundle.events:
        lines.append("\n[관련 사건]")
        for ev in bundle.events[:8]:
            ch = f"ch.{ev.chapter_num} " if ev.chapter_num is not None else ""
            lines.append(f"- {ch}{ev.title}: {_clip(ev.summary, 200)}")
    if bundle.summary_nodes:
        lines.append("\n[요약 트리 기억]")
        for node in bundle.summary_nodes[:8]:
            span = ""
            if node.chapter_start is not None and node.chapter_end is not None:
                span = f" ch.{node.chapter_start}-{node.chapter_end}"
            score = f" score={node.score:.2f}" if node.score is not None else ""
            lines.append(f"- [{node.level}] {node.node_key}{span}{score}: {_clip(node.summary, 260)}")
    if bundle.excerpts:
        lines.append("\n[과거 본문 발췌]")
        for ex in bundle.excerpts[:6]:
            ch = f"ch.{ex.chapter_num} " if ex.chapter_num is not None else ""
            score = f" score={ex.score:.2f}" if ex.score is not None else ""
            lines.append(f"- {ch}{ex.source}{score}: {_clip(ex.snippet, 220)}")
    if bundle.graph_context.strip():
        lines.append("\n[그래프 근방 요약]")
        lines.append(_clip(bundle.graph_context, 900))
    if bundle.warnings:
        lines.append("\n[연속성 주의]")
        for warning in bundle.warnings[:6]:
            lines.append(f"- {_clip(warning, 220)}")
    if len(lines) <= 2:
        lines.append("- 이번 세그먼트와 강하게 연결된 장기 기억을 찾지 못했습니다.")
    return "\n".join(lines).strip()


def compose_memory_query(
    segment_memo: str,
    *,
    previous_text: str = "",
    scene_hint: str = "",
    chapter_state: dict[str, Any] | None = None,
    limit: int = 900,
) -> str:
    state = chapter_state or {}
    state_terms = " ".join(str(v) for v in state.values() if isinstance(v, (str, int, float)))
    query = "\n".join(
        part.strip()
        for part in (segment_memo, scene_hint, state_terms, previous_text[-500:])
        if part and part.strip()
    )
    return _clip(query, limit)


async def build_memory_bundle(
    session: AsyncSession,
    story_id: uuid.UUID,
    chapter_num: int,
    segment_memo: str,
    *,
    previous_text: str = "",
    scene_hint: str = "",
    chapter_state: dict[str, Any] | None = None,
    limit: int = 6,
) -> MemoryBundle:
    """현재 세그먼트에 필요한 장기 기억을 Postgres/RAG/Neo4j에서 자동 수집한다."""
    from app.models import (
        EpisodeChunk,
        StoryEntity,
        StoryEvent,
        StoryRelationship,
        StoryRelationshipEvidence,
    )

    query = compose_memory_query(
        segment_memo,
        previous_text=previous_text,
        scene_hint=scene_hint,
        chapter_state=chapter_state,
    )
    bundle = MemoryBundle(query=query)
    if not query.strip():
        return bundle

    normalized_q = normalize_entity_name(query)
    entity_stmt = (
        select(StoryEntity)
        .where(StoryEntity.story_id == story_id)
        .where(
            or_(
                StoryEntity.name.ilike(f"%{query[:80]}%"),
                StoryEntity.description.ilike(f"%{query[:80]}%"),
                StoryEntity.aliases.cast(Text).ilike(f"%{normalized_q[:80]}%"),
            )
        )
        .order_by(StoryEntity.importance.desc(), StoryEntity.updated_at.desc())
        .limit(limit)
    )
    direct_entities = list((await session.execute(entity_stmt)).scalars().all())
    bundle.entities = [
        MemoryEntityHit(
            id=str(e.id),
            name=e.name,
            entity_type=e.entity_type,
            description=e.description or "",
            importance=e.importance or 3,
        )
        for e in direct_entities
    ]

    try:
        bundle.summary_nodes = [
            MemorySummaryNodeHit(
                id=hit.id,
                node_key=hit.node_key,
                level=hit.level,
                summary=hit.summary,
                chapter_start=hit.chapter_start,
                chapter_end=hit.chapter_end,
                score=hit.score,
                parent_id=hit.parent_id,
                ancestor_ids=hit.ancestor_ids,
            )
            for hit in await search_summary_nodes(
                session,
                story_id,
                query,
                chapter_num=chapter_num,
                limit=limit,
            )
        ]
    except Exception as exc:
        await session.rollback()
        bundle.warnings.append(f"요약 트리 검색 실패: {type(exc).__name__}")

    entity_ids = [e.id for e in direct_entities]
    if entity_ids:
        rel_stmt = (
            select(StoryRelationship, StoryRelationshipEvidence)
            .outerjoin(
                StoryRelationshipEvidence,
                StoryRelationshipEvidence.relationship_id == StoryRelationship.id,
            )
            .where(StoryRelationship.story_id == story_id)
            .where(
                or_(
                    StoryRelationship.source_entity_id.in_(entity_ids),
                    StoryRelationship.target_entity_id.in_(entity_ids),
                )
            )
            .order_by(StoryRelationship.confidence.desc(), StoryRelationship.updated_at.desc())
            .limit(limit)
        )
        rel_rows = (await session.execute(rel_stmt)).all()
        entity_name = {e.id: e.name for e in direct_entities}
        for rel, evidence in rel_rows:
            if rel.source_entity_id not in entity_name:
                src = await session.get(StoryEntity, rel.source_entity_id)
                if src:
                    entity_name[src.id] = src.name
            if rel.target_entity_id not in entity_name:
                tgt = await session.get(StoryEntity, rel.target_entity_id)
                if tgt:
                    entity_name[tgt.id] = tgt.name
            bundle.relationships.append(
                MemoryRelationshipHit(
                    id=str(rel.id),
                    source=entity_name.get(rel.source_entity_id, "(unknown)"),
                    target=entity_name.get(rel.target_entity_id, "(unknown)"),
                    relation_type=rel.relation_type,
                    current_state=rel.current_state or "",
                    evidence=(evidence.evidence_excerpt if evidence else "") or "",
                    confidence=rel.confidence,
                )
            )

    event_stmt = (
        select(StoryEvent)
        .where(StoryEvent.story_id == story_id)
        .where(StoryEvent.chapter_num <= chapter_num)
        .where(or_(StoryEvent.title.ilike(f"%{query[:80]}%"), StoryEvent.summary.ilike(f"%{query[:80]}%")))
        .order_by(StoryEvent.importance.desc(), StoryEvent.chapter_num.desc())
        .limit(limit)
    )
    events = list((await session.execute(event_stmt)).scalars().all())
    bundle.events = [
        MemoryEventHit(
            id=str(e.id),
            title=e.title,
            summary=e.summary or "",
            chapter_num=e.chapter_num,
            importance=e.importance or 3,
        )
        for e in events
    ]

    try:
        for source, obj, score, snippet, episode_id, ch_num in await rag.search_rag_merged(
            session,
            story_id,
            query,
            limit=limit,
        ):
            segment_index = None
            paragraph_index = None
            if isinstance(obj, EpisodeChunk) and isinstance(obj.chunk_meta, dict):
                segment_index = obj.chunk_meta.get("segment_index")
                paragraph_index = obj.chunk_meta.get("paragraph_index")
            bundle.excerpts.append(
                MemoryExcerptHit(
                    source=source,
                    snippet=snippet,
                    chapter_num=ch_num or None,
                    score=score,
                    episode_id=str(episode_id) if episode_id else None,
                    segment_index=segment_index,
                    paragraph_index=paragraph_index,
                )
            )
    except Exception as exc:
        await session.rollback()
        bundle.warnings.append(f"RAG 검색 실패: {type(exc).__name__}")

    if get_settings().graph_enabled:
        try:
            bundle.graph_context = await graph_context_text(story_id, limit=limit)
        except Exception as exc:
            bundle.warnings.append(f"Neo4j 근방 요약 실패: {type(exc).__name__}")

    return bundle
