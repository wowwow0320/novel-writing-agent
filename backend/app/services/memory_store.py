import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Episode,
    GenerationRun,
    StoryEntity,
    StoryEvent,
    StoryRelationship,
    StoryRelationshipEvidence,
)
from app.services import llm
from app.services.memory_retrieval import normalize_entity_name

logger = logging.getLogger(__name__)

ENTITY_TYPES = {"CHAR", "LOC", "ITEM", "EVENT", "ORG", "SITUATION"}


def _coerce_entity_type(raw: Any) -> str:
    value = str(raw or "CHAR").strip().upper()
    if value in ENTITY_TYPES:
        return value
    if value in {"PLACE", "LOCATION"}:
        return "LOC"
    if value in {"ORGANIZATION", "GROUP"}:
        return "ORG"
    return "CHAR"


def _coerce_int(raw: Any, default: int = 3, low: int = 1, high: int = 5) -> int:
    try:
        value = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _coerce_float(raw: Any, default: float | None = None) -> float | None:
    if raw is None:
        return default
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return default


def _metadata_aliases(meta: dict[str, Any]) -> list[str]:
    aliases = meta.get("aliases") or meta.get("alias") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list):
        return []
    out: list[str] = []
    for value in aliases:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def bible_entry_to_entity_payload(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if not meta and isinstance(row.get("extra"), dict):
        meta = row.get("extra") or {}
    name = str(row.get("name", "") or "").strip()
    return {
        "entity_type": _coerce_entity_type(row.get("category")),
        "name": name,
        "normalized_name": normalize_entity_name(name),
        "aliases": _metadata_aliases(meta),
        "description": str(row.get("description", "") or "").strip(),
        "status": str(meta.get("status", "unknown") or "unknown").strip().lower(),
        "importance": _coerce_int(meta.get("importance", 3)),
        "metadata": dict(meta),
    }


def graph_entity_to_payload(row: dict[str, Any]) -> dict[str, Any]:
    name = str(row.get("name", "") or "").strip()
    return {
        "entity_type": _coerce_entity_type(row.get("type")),
        "name": name,
        "normalized_name": normalize_entity_name(name),
        "aliases": _metadata_aliases(row),
        "description": str(row.get("origin_hint", "") or "").strip(),
        "status": str(row.get("status", "unknown") or "unknown").strip().lower(),
        "importance": _coerce_int(row.get("importance", 3)),
        "metadata": {"origin_hint": str(row.get("origin_hint", "") or "").strip()},
    }


def _merge_aliases(existing: list[str] | None, incoming: list[str] | None) -> list[str] | None:
    merged: list[str] = []
    for value in (existing or []) + (incoming or []):
        text = str(value or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged or None


async def upsert_entity_payload(
    session: AsyncSession,
    story_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    chapter_num: int | None = None,
) -> StoryEntity | None:
    name = str(payload.get("name", "") or "").strip()
    if not name:
        return None
    entity_type = _coerce_entity_type(payload.get("entity_type"))
    normalized = normalize_entity_name(payload.get("normalized_name") or name)
    r = await session.execute(
        select(StoryEntity)
        .where(StoryEntity.story_id == story_id)
        .where(StoryEntity.entity_type == entity_type)
        .where(StoryEntity.normalized_name == normalized)
    )
    row = r.scalar_one_or_none()
    if row is None:
        row = StoryEntity(
            story_id=story_id,
            entity_type=entity_type,
            name=name,
            normalized_name=normalized,
            aliases=payload.get("aliases") or None,
            description=str(payload.get("description", "") or "").strip() or None,
            status=str(payload.get("status", "unknown") or "unknown").strip().lower(),
            importance=_coerce_int(payload.get("importance", 3)),
            first_chapter_num=chapter_num,
            last_chapter_num=chapter_num,
            extra=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
        )
        session.add(row)
        await session.flush()
        return row

    row.aliases = _merge_aliases(row.aliases, payload.get("aliases") or [])
    new_desc = str(payload.get("description", "") or "").strip()
    if new_desc and (not row.description or len(new_desc) > len(row.description)):
        row.description = new_desc
    status = str(payload.get("status", "") or "").strip().lower()
    if status and status != "unknown":
        row.status = status
    row.importance = max(row.importance or 3, _coerce_int(payload.get("importance", 3)))
    if chapter_num is not None:
        row.first_chapter_num = (
            chapter_num
            if row.first_chapter_num is None
            else min(row.first_chapter_num, chapter_num)
        )
        row.last_chapter_num = (
            chapter_num
            if row.last_chapter_num is None
            else max(row.last_chapter_num, chapter_num)
        )
    meta = row.extra if isinstance(row.extra, dict) else {}
    incoming_meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    row.extra = {**meta, **incoming_meta} or None
    await session.flush()
    return row


async def upsert_bible_entries_to_memory(
    session: AsyncSession,
    story_id: uuid.UUID,
    rows: list[dict[str, Any]],
) -> list[StoryEntity]:
    entities: list[StoryEntity] = []
    for row in rows:
        ent = await upsert_entity_payload(session, story_id, bible_entry_to_entity_payload(row))
        if ent is not None:
            entities.append(ent)
    await _embed_entities(session, entities)
    return entities


async def upsert_chapter_events_to_memory(
    session: AsyncSession,
    story_id: uuid.UUID,
    episode: Episode,
    events: list[dict[str, Any]] | None,
) -> list[StoryEvent]:
    out: list[StoryEvent] = []
    if not events:
        return out
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        title = str(ev.get("title") or ev.get("name") or f"사건 {idx + 1}").strip()
        normalized = normalize_entity_name(title)
        r = await session.execute(
            select(StoryEvent)
            .where(StoryEvent.story_id == story_id)
            .where(StoryEvent.source_episode_id == episode.id)
            .where(StoryEvent.normalized_title == normalized)
        )
        row = r.scalar_one_or_none()
        if row is None:
            row = StoryEvent(
                story_id=story_id,
                title=title,
                normalized_title=normalized,
                source_episode_id=episode.id,
                chapter_num=episode.chapter_num,
                event_order=idx,
                importance=_coerce_int(ev.get("importance", 3)),
            )
            session.add(row)
        row.summary = str(ev.get("summary") or ev.get("description") or "").strip() or row.summary
        row.cause = str(ev.get("cause") or "").strip() or row.cause
        row.effect = str(ev.get("outcome") or ev.get("effect") or "").strip() or row.effect
        row.importance = max(row.importance or 3, _coerce_int(ev.get("importance", 3)))
        meta = row.extra if isinstance(row.extra, dict) else {}
        row.extra = {**meta, "raw_event": ev}
        out.append(row)
    await session.flush()
    await _embed_events(session, out)
    return out


async def upsert_graph_facts_to_memory(
    session: AsyncSession,
    story_id: uuid.UUID,
    facts: dict[str, list[dict[str, Any]]],
    *,
    episode: Episode | None = None,
    origin_kind: str = "episode",
) -> dict[str, int]:
    entity_by_name: dict[str, StoryEntity] = {}
    for raw in facts.get("entities", []):
        payload = graph_entity_to_payload(raw)
        ent = await upsert_entity_payload(
            session,
            story_id,
            payload,
            chapter_num=episode.chapter_num if episode else None,
        )
        if ent is not None:
            entity_by_name[str(raw.get("name", "")).strip()] = ent

    relationships_count = 0
    for raw in facts.get("relations", []):
        sub = str(raw.get("subject", "") or "").strip()
        obj = str(raw.get("object", "") or "").strip()
        if not sub or not obj or sub == obj:
            continue
        source = entity_by_name.get(sub)
        target = entity_by_name.get(obj)
        if source is None:
            source = await upsert_entity_payload(
                session,
                story_id,
                graph_entity_to_payload({"name": sub, "type": raw.get("subject_type", "CHAR")}),
                chapter_num=episode.chapter_num if episode else None,
            )
        if target is None:
            target = await upsert_entity_payload(
                session,
                story_id,
                graph_entity_to_payload({"name": obj, "type": raw.get("object_type", "CHAR")}),
                chapter_num=episode.chapter_num if episode else None,
            )
        if source is None or target is None:
            continue
        relation_type = str(raw.get("relation", "INVOLVED_IN") or "INVOLVED_IN").strip().upper()
        r = await session.execute(
            select(StoryRelationship)
            .where(StoryRelationship.story_id == story_id)
            .where(StoryRelationship.source_entity_id == source.id)
            .where(StoryRelationship.target_entity_id == target.id)
            .where(StoryRelationship.relation_type == relation_type)
        )
        rel = r.scalar_one_or_none()
        confidence = _coerce_float(raw.get("confidence"), 0.7)
        if rel is None:
            rel = StoryRelationship(
                story_id=story_id,
                source_entity_id=source.id,
                target_entity_id=target.id,
                relation_type=relation_type,
                current_state=str(raw.get("current_state") or relation_type).strip().lower(),
                confidence=confidence,
                first_chapter_num=episode.chapter_num if episode else None,
                last_chapter_num=episode.chapter_num if episode else None,
            )
            session.add(rel)
            await session.flush()
        else:
            rel.current_state = str(raw.get("current_state") or rel.current_state or relation_type).strip().lower()
            rel.confidence = max(rel.confidence or 0.0, confidence or 0.0)
            if episode is not None:
                rel.first_chapter_num = (
                    episode.chapter_num
                    if rel.first_chapter_num is None
                    else min(rel.first_chapter_num, episode.chapter_num)
                )
                rel.last_chapter_num = (
                    episode.chapter_num
                    if rel.last_chapter_num is None
                    else max(rel.last_chapter_num, episode.chapter_num)
                )
        session.add(
            StoryRelationshipEvidence(
                story_id=story_id,
                relationship_id=rel.id,
                episode_id=episode.id if episode else None,
                evidence_excerpt=str(raw.get("context", "") or "").strip()[:1000] or None,
                confidence=confidence,
                origin_kind=origin_kind,
            )
        )
        relationships_count += 1
    await session.flush()
    await _embed_entities(session, list(entity_by_name.values()))
    return {"entities": len(entity_by_name), "relationships": relationships_count}


async def record_generation_run(
    session: AsyncSession,
    *,
    story_id: uuid.UUID,
    episode_id: uuid.UUID | None,
    run_mode: str,
    memory_mode: str,
    segments: list[dict[str, Any]] | None,
    memory_trace: list[dict[str, Any]] | None,
    revision_payload: dict[str, Any] | None = None,
    status: str = "completed",
) -> GenerationRun:
    row = GenerationRun(
        story_id=story_id,
        episode_id=episode_id,
        run_mode=run_mode,
        memory_mode=memory_mode,
        segments=segments,
        memory_trace=memory_trace,
        revision_payload=revision_payload,
        status=status,
    )
    session.add(row)
    await session.flush()
    return row


async def _embed_entities(session: AsyncSession, rows: list[StoryEntity]) -> None:
    if not rows or get_settings().embedding_provider == "none":
        return
    targets = [row for row in rows if row.name]
    if not targets:
        return
    try:
        texts = [f"[{row.entity_type}] {row.name}\n{row.description or ''}".strip() for row in targets]
        embeddings = await llm.embed_texts(texts)
    except Exception as exc:
        logger.warning("story_entities 임베딩 실패: %s", exc)
        return
    for row, vec in zip(targets, embeddings):
        if vec:
            row.embedding = vec
    await session.flush()


async def _embed_events(session: AsyncSession, rows: list[StoryEvent]) -> None:
    if not rows or get_settings().embedding_provider == "none":
        return
    try:
        texts = [f"[EVENT] {row.title}\n{row.summary or ''}".strip() for row in rows]
        embeddings = await llm.embed_texts(texts)
    except Exception as exc:
        logger.warning("story_events 임베딩 실패: %s", exc)
        return
    for row, vec in zip(rows, embeddings):
        if vec:
            row.embedding = vec
    await session.flush()
