import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import BibleCategory, StoryBibleEntry, StoryEvent, StoryRelationship
from app.services import llm, rag
from app.services.graph_sync import extract_graph_facts, project_episode_memory_to_graph
from app.services.memory_retrieval import normalize_entity_name
from app.services.memory_store import upsert_bible_entries_to_memory, upsert_graph_facts_to_memory
from app.services.story_pipeline import extract_foundation, foundation_to_bible_items
from app.services.summary_tree import embed_summary_nodes, upsert_summary_node

logger = logging.getLogger(__name__)


def _parse_category(value: Any) -> BibleCategory:
    raw = str(value or "CHAR").strip().upper()
    try:
        return BibleCategory(raw)
    except ValueError:
        return BibleCategory.char


def foundation_summary_text(foundation: dict[str, Any]) -> str:
    premise = str(foundation.get("premise") or "").strip()
    entities = foundation.get("entities") if isinstance(foundation.get("entities"), dict) else {}
    lines: list[str] = []
    if premise:
        lines.append(f"대전제: {premise}")
    chars = entities.get("characters") if isinstance(entities.get("characters"), list) else []
    if chars:
        lines.append("[핵심 인물]")
        for char in chars[:12]:
            if not isinstance(char, dict):
                continue
            traits = ", ".join(str(x) for x in (char.get("traits") or []) if str(x).strip())
            goals = ", ".join(str(x) for x in (char.get("goals") or []) if str(x).strip())
            lines.append(f"- {char.get('name', 'unknown')}: {traits or '특성 미정'} / 목표: {goals or '미정'}")
    backgrounds = entities.get("backgrounds") if isinstance(entities.get("backgrounds"), list) else []
    if backgrounds:
        lines.append("[세계관/장소]")
        for bg in backgrounds[:10]:
            if not isinstance(bg, dict):
                continue
            constraints = ", ".join(str(x) for x in (bg.get("constraints") or []) if str(x).strip())
            lines.append(
                f"- {bg.get('place', 'unknown')}: 시대 {bg.get('era', '')}, 분위기 {bg.get('mood', '')}, 제약 {constraints}"
            )
    events = entities.get("events") if isinstance(entities.get("events"), list) else []
    if events:
        lines.append("[초기 사건]")
        for event in events[:12]:
            if not isinstance(event, dict):
                continue
            lines.append(
                f"- {event.get('title', 'unknown')}: 원인 {event.get('cause', '')}, 결과 {event.get('outcome', '')}, 위험 {event.get('stakes', '')}"
            )
    return "\n".join(line for line in lines if line.strip()).strip()


def foundation_to_event_payloads(foundation: dict[str, Any]) -> list[dict[str, Any]]:
    entities = foundation.get("entities") if isinstance(foundation.get("entities"), dict) else {}
    events = entities.get("events") if isinstance(entities.get("events"), list) else []
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(events):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or f"세계관 사건 {idx + 1}").strip()
        if not title:
            continue
        out.append(
            {
                "title": title,
                "summary": str(raw.get("summary") or raw.get("stakes") or "").strip(),
                "cause": str(raw.get("cause") or "").strip(),
                "effect": str(raw.get("outcome") or raw.get("effect") or "").strip(),
                "importance": 4,
                "metadata": {"source": "world_setting", "raw_event": raw},
            }
        )
    premise = str(foundation.get("premise") or "").strip()
    if premise:
        out.append(
            {
                "title": "작품 대전제",
                "summary": premise,
                "cause": "",
                "effect": "",
                "importance": 5,
                "metadata": {"source": "world_setting", "kind": "premise"},
            }
        )
    return out


async def _upsert_bible_items(
    session: AsyncSession,
    story_id: uuid.UUID,
    items: list[dict[str, Any]],
) -> list[StoryBibleEntry]:
    rows: list[StoryBibleEntry] = []
    for item in items:
        category = _parse_category(item.get("category"))
        name = str(item.get("name", "") or "").strip() or "이름 미상"
        desc = str(item.get("description", "") or "").strip() or None
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        r = await session.execute(
            select(StoryBibleEntry)
            .where(StoryBibleEntry.story_id == story_id)
            .where(StoryBibleEntry.category == category)
            .where(StoryBibleEntry.name == name)
            .limit(1)
        )
        row = r.scalar_one_or_none()
        if row is None:
            row = StoryBibleEntry(
                story_id=story_id,
                category=category,
                name=name,
                description=desc,
                extra=meta or None,
            )
            session.add(row)
        else:
            if desc and (not row.description or len(desc) > len(row.description)):
                row.description = desc
            existing = row.extra if isinstance(row.extra, dict) else {}
            row.extra = {**existing, **meta} or None
        rows.append(row)
    await session.flush()
    await rag.embed_bible_entries(session, rows)
    return rows


async def _upsert_foundation_events(
    session: AsyncSession,
    story_id: uuid.UUID,
    events: list[dict[str, Any]],
) -> list[StoryEvent]:
    rows: list[StoryEvent] = []
    for idx, payload in enumerate(events):
        title = str(payload.get("title") or f"세계관 사건 {idx + 1}").strip()
        normalized = normalize_entity_name(title)
        r = await session.execute(
            select(StoryEvent)
            .where(StoryEvent.story_id == story_id)
            .where(StoryEvent.source_episode_id.is_(None))
            .where(StoryEvent.normalized_title == normalized)
            .limit(1)
        )
        row = r.scalar_one_or_none()
        if row is None:
            row = StoryEvent(
                story_id=story_id,
                title=title,
                normalized_title=normalized,
                event_order=idx,
                importance=int(payload.get("importance") or 4),
                extra=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
            )
            session.add(row)
        row.summary = str(payload.get("summary") or "").strip() or row.summary
        row.cause = str(payload.get("cause") or "").strip() or row.cause
        row.effect = str(payload.get("effect") or "").strip() or row.effect
        rows.append(row)
    await session.flush()
    if get_settings().embedding_provider != "none" and rows:
        try:
            embeddings = await llm.embed_texts([f"[EVENT] {row.title}\n{row.summary or ''}" for row in rows])
            for row, vec in zip(rows, embeddings):
                if vec:
                    row.embedding = vec
            await session.flush()
        except Exception as exc:
            logger.warning("foundation story_events 임베딩 실패: %s", exc)
    return rows


async def sync_foundation_memory(
    session: AsyncSession,
    story_id: uuid.UUID,
    world_text: str,
    origin: str = "world_setting",
) -> dict[str, Any]:
    text = (world_text or "").strip()
    result: dict[str, Any] = {
        "bible": 0,
        "entities": 0,
        "events": 0,
        "relationships": 0,
        "summary_nodes": 0,
        "graph_sync": {"enabled": False, "entities": 0, "events": 0, "relations": 0},
    }
    if not text:
        return result
    try:
        foundation = await extract_foundation(text)
        bible_items = foundation_to_bible_items(foundation)
        bible_rows = await _upsert_bible_items(session, story_id, bible_items)
        result["bible"] = len(bible_rows)

        memory_entities = await upsert_bible_entries_to_memory(session, story_id, bible_items)
        result["entities"] = len(memory_entities)

        event_rows = await _upsert_foundation_events(
            session,
            story_id,
            foundation_to_event_payloads(foundation),
        )
        result["events"] = len(event_rows)

        try:
            facts = await extract_graph_facts(text)
            fact_counts = await upsert_graph_facts_to_memory(
                session,
                story_id,
                facts,
                episode=None,
                origin_kind=origin,
            )
            result["relationships"] = fact_counts.get("relationships", 0)
            result["entities"] = max(int(result["entities"]), fact_counts.get("entities", 0))
        except Exception as exc:
            logger.warning("foundation graph fact 추출/저장 실패: %s", exc)
            result["relationship_error"] = str(exc)[:1200]

        rel_rows = list(
            (
                await session.execute(
                    select(StoryRelationship)
                    .where(StoryRelationship.story_id == story_id)
                    .order_by(StoryRelationship.updated_at.desc())
                    .limit(80)
                )
            )
            .scalars()
            .all()
        )
        summary = foundation_summary_text(foundation) or text[:3000]
        node = await upsert_summary_node(
            session,
            story_id=story_id,
            node_key="foundation",
            level="foundation",
            summary=summary,
            depth=0,
            path=["foundation"],
            source_episode_ids=None,
            entity_ids=[str(row.id) for row in memory_entities] or None,
            event_ids=[str(row.id) for row in event_rows] or None,
            relationship_ids=[str(row.id) for row in rel_rows] or None,
            coverage_score=1.0,
            stale=False,
            metadata={"origin": origin, "world_setting_chars": len(text)},
        )
        result["summary_nodes"] = 1
        result["summary_node_id"] = str(node.id)
        result["embedded"] = await embed_summary_nodes(session, [node])

        if get_settings().graph_enabled:
            try:
                result["graph_sync"] = await project_episode_memory_to_graph(session, story_id, None)
            except RuntimeError as exc:
                logger.warning("Neo4j 동기화 실패(foundation): %s", exc)
                result["graph_sync"] = {
                    "enabled": True,
                    "entities": 0,
                    "events": 0,
                    "relations": 0,
                    "error": str(exc)[:1200],
                }
    except Exception as exc:
        logger.warning("foundation memory sync 실패: %s", exc)
        result["error"] = str(exc)[:1200]
    return result
