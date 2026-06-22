import json
import math
import re
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services import llm
from app.services.episode_text import split_paragraphs
from app.services.prompts import (
    chapter_flow_alignment_system,
    chapter_flow_alignment_user,
    chapter_summary_system,
    event_extract_system,
    event_extract_user,
    foundation_extract_system,
    foundation_extract_user,
    paragraph_summary_system,
    question_classifier_system,
    question_classifier_user,
    semantic_route_system,
    semantic_route_user,
    work_summary_rollup_system,
    work_summary_rollup_user,
)
from app.models import BibleCategory, Story, StoryBibleEntry

WORLD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["premise", "keywords", "entities"],
    "properties": {
        "premise": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "entities": {
            "type": "object",
            "required": ["characters", "backgrounds", "events"],
            "properties": {
                "characters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "traits", "appearance", "goals"],
                        "properties": {
                            "name": {"type": "string"},
                            "traits": {"type": "array", "items": {"type": "string"}},
                            "appearance": {"type": "array", "items": {"type": "string"}},
                            "goals": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "backgrounds": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["place", "era", "mood", "constraints"],
                        "properties": {
                            "place": {"type": "string"},
                            "era": {"type": "string"},
                            "mood": {"type": "string"},
                            "constraints": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["title", "cause", "outcome", "stakes"],
                        "properties": {
                            "title": {"type": "string"},
                            "cause": {"type": "string"},
                            "outcome": {"type": "string"},
                            "stakes": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _extract_json_array(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
        return []
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        try:
            parsed = json.loads(m.group(0))
            return [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []


def _as_text_list(value: Any) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _as_named_entity_list(value: Any) -> list[str]:
    """질문 분류기의 인물/장소 목록(문자열 또는 {name: ...} 객체)."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
        elif isinstance(item, dict):
            n = str(item.get("name", "")).strip()
            if n:
                out.append(n)
    return out


def _normalize_foundation(data: dict[str, Any]) -> dict[str, Any]:
    entities = data.get("entities") if isinstance(data.get("entities"), dict) else {}
    chars: list[dict[str, Any]] = []
    for row in entities.get("characters", []) if isinstance(entities.get("characters"), list) else []:
        if not isinstance(row, dict):
            continue
        chars.append(
            {
                "name": str(row.get("name", "")).strip() or "unknown",
                "traits": _as_text_list(row.get("traits")),
                "appearance": _as_text_list(row.get("appearance")),
                "goals": _as_text_list(row.get("goals")),
            }
        )
    bgs: list[dict[str, Any]] = []
    for row in entities.get("backgrounds", []) if isinstance(entities.get("backgrounds"), list) else []:
        if not isinstance(row, dict):
            continue
        bgs.append(
            {
                "place": str(row.get("place", "")).strip() or "unknown",
                "era": str(row.get("era", "")).strip() or "unknown",
                "mood": str(row.get("mood", "")).strip() or "unknown",
                "constraints": _as_text_list(row.get("constraints")),
            }
        )
    evs: list[dict[str, Any]] = []
    for row in entities.get("events", []) if isinstance(entities.get("events"), list) else []:
        if not isinstance(row, dict):
            continue
        evs.append(
            {
                "title": str(row.get("title", "")).strip() or "unknown",
                "cause": str(row.get("cause", "")).strip() or "",
                "outcome": str(row.get("outcome", "")).strip() or "",
                "stakes": str(row.get("stakes", "")).strip() or "",
            }
        )
    return {
        "premise": str(data.get("premise", "")).strip(),
        "keywords": _as_text_list(data.get("keywords")),
        "entities": {
            "characters": chars,
            "backgrounds": bgs,
            "events": evs,
        },
    }


def _parse_bible_category(cat_s: str) -> BibleCategory:
    u = (cat_s or "CHAR").upper().strip()
    mapping = {
        "CHAR": BibleCategory.char,
        "LOC": BibleCategory.loc,
        "ITEM": BibleCategory.item,
        "EVENT": BibleCategory.event,
    }
    return mapping.get(u, BibleCategory.char)


async def seed_story_bible_from_world_text(
    session: AsyncSession,
    story_id: uuid.UUID,
    world_text: str,
) -> int:
    """배경 텍스트를 분석해 설정 노트에 선반영하고 임베딩합니다."""
    from app.services import rag

    if not (world_text or "").strip():
        return 0
    foundation = await extract_foundation(world_text)
    items = foundation_to_bible_items(foundation)
    if not items:
        return 0
    created: list[StoryBibleEntry] = []
    for item in items:
        cat = _parse_bible_category(str(item.get("category", "CHAR")))
        name = str(item.get("name", "")).strip() or "이름 미상"
        desc = item.get("description")
        meta = item.get("metadata")
        row = StoryBibleEntry(
            story_id=story_id,
            category=cat,
            name=name,
            description=str(desc) if desc else None,
            extra=meta if isinstance(meta, dict) else None,
        )
        session.add(row)
        created.append(row)
    await session.flush()
    await rag.embed_bible_entries(session, created)
    return len(created)


async def extract_foundation(story_input: str) -> dict[str, Any]:
    raw = await llm.complete_chat(
        foundation_extract_system(),
        foundation_extract_user(story_input),
        temperature=0.2,
    )
    parsed = _extract_json_object(raw)
    return _normalize_foundation(parsed)


async def classify_required_elements(draft: str) -> dict[str, Any]:
    raw = await llm.complete_chat(
        question_classifier_system(),
        question_classifier_user(draft),
        temperature=0.0,
    )
    parsed = _extract_json_object(raw)
    template = {
        "who": {"present": False, "reason": "초안에서 인물 주체가 충분히 확인되지 않음"},
        "where": {"present": False, "reason": "초안에서 공간/배경 정보가 충분하지 않음"},
        "what": {"present": False, "reason": "행동/사건 정보가 충분하지 않음"},
    }
    out: dict[str, Any] = {}
    for key in ("who", "where", "what"):
        node = parsed.get(key) if isinstance(parsed.get(key), dict) else {}
        out[key] = {
            "present": bool(node.get("present", template[key]["present"])),
            "reason": str(node.get("reason", template[key]["reason"])).strip() or template[key]["reason"],
        }
    out["missing"] = [k for k in ("who", "where", "what") if not out[k]["present"]]
    ne = parsed.get("named_entities") if isinstance(parsed.get("named_entities"), dict) else {}
    out["named_entities"] = {
        "characters": _as_named_entity_list(ne.get("characters")) if isinstance(ne, dict) else [],
        "places": _as_named_entity_list(ne.get("places")) if isinstance(ne, dict) else [],
    }
    out["missing_names"] = _as_text_list(parsed.get("missing_names"))
    out["suggested_questions"] = _as_text_list(parsed.get("suggested_questions"))[:5]
    return out


def decide_generation_mode(
    draft: str,
    sentence_count: int | None = None,
    complexity_hint: float | None = None,
) -> dict[str, Any]:
    text = (draft or "").strip()
    chars = len(text)
    sentences = sentence_count if sentence_count is not None else max(1, len(re.findall(r"[.!?。！？\n]+", text)))
    unique_ratio = len(set(text.split())) / max(len(text.split()), 1)
    complexity = complexity_hint if complexity_hint is not None else min(1.0, (unique_ratio + (sentences / 80)) / 2)

    threshold_chars = 1200
    threshold_sentences = 20
    threshold_complexity = 0.55

    multi = chars >= threshold_chars or sentences >= threshold_sentences or complexity >= threshold_complexity
    reason = []
    if chars >= threshold_chars:
        reason.append(f"길이({chars}자)가 임계값({threshold_chars}) 이상")
    if sentences >= threshold_sentences:
        reason.append(f"문장 수({sentences})가 임계값({threshold_sentences}) 이상")
    if complexity >= threshold_complexity:
        reason.append(f"복잡도({complexity:.2f})가 임계값({threshold_complexity}) 이상")
    if not reason:
        reason.append("입력이 짧고 단순해 단일 생성이 적합")
    return {
        "mode": "multi_step" if multi else "single_pass",
        "metrics": {
            "char_count": chars,
            "sentence_count": sentences,
            "complexity": round(complexity, 4),
        },
        "thresholds": {
            "char_count": threshold_chars,
            "sentence_count": threshold_sentences,
            "complexity": threshold_complexity,
        },
        "reason": "; ".join(reason),
    }


async def build_hierarchical_summary(
    text: str,
    paragraph_max_chars: int = 220,
    chapter_max_chars: int = 420,
) -> dict[str, Any]:
    paragraphs = split_paragraphs(text)
    paragraph_summaries: list[str] = []
    for para in paragraphs:
        summ = await llm.complete_chat(
            paragraph_summary_system(paragraph_max_chars),
            para,
            temperature=0.2,
        )
        paragraph_summaries.append(summ.strip())

    event_rows: list[dict[str, Any]] = []
    event_source = "\n\n".join(paragraph_summaries) if paragraph_summaries else (text or "")
    if event_source.strip():
        events_raw = await llm.complete_chat(
            event_extract_system(),
            event_extract_user(event_source),
            temperature=0.15,
        )
        event_rows = _extract_json_array(events_raw)

    event_blob = "\n".join(
        f"- {idx+1}. {row.get('title', '사건')} | 원인: {row.get('cause', '')} | 결과: {row.get('outcome', '')}"
        for idx, row in enumerate(event_rows)
    )
    chapter_summary = await llm.complete_chat(
        chapter_summary_system(chapter_max_chars),
        event_blob or ("\n".join(paragraph_summaries) if paragraph_summaries else text),
        temperature=0.2,
    )
    return {
        "paragraph_summaries": paragraph_summaries,
        "events": event_rows,
        "chapter_summary": chapter_summary.strip(),
    }


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = (text or "").lower()
    return any(t in lowered for t in terms)


def _vectorize_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in re.findall(r"[a-zA-Z가-힣0-9]+", (text or "").lower()):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _transition_score(prev: str, curr: str) -> float:
    """이전 끝과 현재 시작의 어휘 겹침(0~1). 문장 연결성 휴리스틱."""
    a = (prev or "")[-140:].lower()
    b = (curr or "")[:140].lower()
    if not a.strip() or not b.strip():
        return 0.45
    ta = set(re.findall(r"[가-힣a-z]{2,}", a))
    tb = set(re.findall(r"[가-힣a-z]{2,}", b))
    if not ta or not tb:
        return 0.45
    inter = len(ta & tb)
    return inter / max(1, min(len(ta), len(tb)))


def _cosine_similarity(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for k, va in a.items():
        dot += va * b.get(k, 0)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def logic_consistency_harness(
    previous_text: str,
    current_text: str,
    *,
    allow_discontinuity: bool = False,
) -> dict[str, Any]:
    prev = previous_text or ""
    curr = current_text or ""
    issues: list[str] = []
    dead_markers = ["죽었다", "사망", "숨이 멎", "죽은"]
    alive_markers = ["말했다", "웃었다", "걸었다", "등장", "살아"]
    if _contains_any(prev, dead_markers) and _contains_any(curr, alive_markers):
        issues.append("사망 처리된 인물이 후속 문단에서 생존 상태로 다시 등장할 가능성")
    if _contains_any(prev, ["밤", "자정", "한밤중"]) and _contains_any(curr, ["아침", "해가 뜨", "정오"]):
        issues.append("시간대가 급격히 전환됨(의도적 장면 전환 여부 확인 필요)")

    sim = _cosine_similarity(_vectorize_counts(prev), _vectorize_counts(curr))
    trans = _transition_score(prev, curr)
    needs = bool(issues) or (not allow_discontinuity and trans < 0.06 and sim < 0.12)
    if allow_discontinuity:
        needs = False
    return {
        "cosine_similarity": round(sim, 4),
        "transition_score": round(trans, 4),
        "issues": issues,
        "needs_user_decision": needs,
    }


def foundation_to_bible_items(foundation: dict[str, Any]) -> list[dict[str, Any]]:
    """배경 추출 JSON을 바이블 저장용 항목 배열로 변환."""
    norm = _normalize_foundation(foundation)
    items: list[dict[str, Any]] = []
    for c in norm["entities"]["characters"]:
        traits = ", ".join(c.get("traits", []))
        app = ", ".join(c.get("appearance", []))
        goals = ", ".join(c.get("goals", []))
        desc = " / ".join(x for x in [traits, app] if x).strip()
        if goals:
            desc = (desc + "\n목표: " + goals).strip() if desc else "목표: " + goals
        items.append(
            {
                "category": "CHAR",
                "name": c.get("name", "unknown"),
                "description": desc or "(인물)",
                "metadata": {"source": "world_setting", "importance": 4},
            }
        )
    for bg in norm["entities"]["backgrounds"]:
        items.append(
            {
                "category": "LOC",
                "name": bg.get("place", "unknown"),
                "description": (
                    f"시대: {bg.get('era', '')}, 분위기: {bg.get('mood', '')}, "
                    f"제약: {', '.join(bg.get('constraints', []))}"
                ),
                "metadata": {"source": "world_setting", "importance": 3},
            }
        )
    for ev in norm["entities"]["events"]:
        items.append(
            {
                "category": "EVENT",
                "name": ev.get("title", "unknown"),
                "description": (
                    f"원인: {ev.get('cause', '')}\n결과: {ev.get('outcome', '')}\n위험: {ev.get('stakes', '')}"
                ),
                "metadata": {"source": "world_setting", "importance": 4},
            }
        )
    prem = (norm.get("premise") or "").strip()
    if prem:
        items.append(
            {
                "category": "EVENT",
                "name": "작품 대전제",
                "description": prem,
                "metadata": {"source": "world_setting", "importance": 5},
            }
        )
    return items


def split_draft_for_multi_step(text: str, max_chunk_chars: int = 900) -> list[str]:
    """긴 메모를 장면 단위로 나누어 순차 생성할 때 사용."""
    t = (text or "").strip()
    if not t:
        return []
    paras = split_paragraphs(t)
    if len(paras) > 1:
        return paras
    if len(t) <= max_chunk_chars:
        return [t]
    chunks: list[str] = []
    i = 0
    while i < len(t):
        chunks.append(t[i : i + max_chunk_chars])
        i += max_chunk_chars
    return chunks if chunks else [t]


def semantic_route_fallback(message: str) -> dict[str, Any]:
    m = (message or "").strip().lower()
    if any(x in m for x in ["?", "？", "어떻게", "왜 ", "왜?", "무엇", "누구", "뭘"]):
        return {"intent": "question", "confidence": 0.55, "rationale": "휴리스틱: 질문 형태"}
    if any(x in m for x in ["써", "작성", "초안", "이어", "장면", "쓰"]):
        return {"intent": "create", "confidence": 0.5, "rationale": "휴리스틱: 생성 요청"}
    if any(x in m for x in ["고쳐", "수정", "다듬", "톤", "문체", "바꿔"]):
        return {"intent": "revise", "confidence": 0.5, "rationale": "휴리스틱: 수정 요청"}
    return {"intent": "other", "confidence": 0.4, "rationale": "휴리스틱: 기타"}


async def semantic_route_user_intent(message: str) -> dict[str, Any]:
    try:
        raw = await llm.complete_chat(
            semantic_route_system(),
            semantic_route_user(message),
            temperature=0.0,
        )
        parsed = _extract_json_object(raw)
        intent = str(parsed.get("intent", "other")).strip().lower()
        if intent not in ("question", "create", "revise", "other"):
            intent = "other"
        conf = float(parsed.get("confidence", 0.5) or 0.5)
        conf = max(0.0, min(1.0, conf))
        rationale = str(parsed.get("rationale", "")).strip() or "모델 분류"
        return {"intent": intent, "confidence": conf, "rationale": rationale}
    except (ValueError, RuntimeError):
        return semantic_route_fallback(message)


async def bridge_continuity_bundle(
    session: AsyncSession,
    story_id: uuid.UUID,
    previous_text: str,
    current_text: str,
    *,
    chapter_summary: str | None,
    chapter_events_blob: str | None,
    allow_discontinuity: bool,
    top_k: int,
) -> dict[str, Any]:
    from app.models import EpisodeChunk
    from app.services import rag

    logic = logic_consistency_harness(
        previous_text,
        current_text,
        allow_discontinuity=allow_discontinuity,
    )
    q = ((current_text or "").strip()[:900] or (previous_text or "").strip()[:400])[:900]
    merged = await rag.search_rag_merged(session, story_id, q, max(3, min(12, top_k)))
    hits: list[dict[str, Any]] = []
    for src, obj, score, snip, eid, chnum in merged:
        if src != "episode" or not isinstance(obj, EpisodeChunk):
            continue
        meta = obj.chunk_meta if isinstance(obj.chunk_meta, dict) else {}
        hits.append(
            {
                "source": "episode",
                "snippet": (snip or "")[:1200],
                "score": score,
                "episode_id": str(eid) if eid else None,
                "chapter_num": chnum,
                "category": obj.category,
                "color_tag": meta.get("color_tag"),
                "segment_index": meta.get("segment_index"),
                "paragraph_index": meta.get("paragraph_index"),
            }
        )
    note: str | None = None
    if (chapter_summary or "").strip():
        try:
            note = await llm.complete_chat(
                chapter_flow_alignment_system(),
                chapter_flow_alignment_user(
                    chapter_summary or "",
                    chapter_events_blob or "",
                    current_text or "",
                ),
                temperature=0.15,
            )
            note = (note or "").strip()[:2000] or None
        except (ValueError, RuntimeError):
            note = None
    return {"logic": logic, "top_k_hits": hits, "chapter_flow_note": note}


def events_for_jsonb(rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not rows:
        return None
    out: list[dict[str, Any]] = []
    for ev in rows:
        if not isinstance(ev, dict):
            continue
        out.append({str(k): v for k, v in ev.items()})
    return out or None


async def hierarchical_from_block_texts(
    blocks: list[str],
    paragraph_max_chars: int = 220,
    chapter_max_chars: int = 420,
) -> dict[str, Any]:
    """에피소드 본문 블록(세그먼트)마다 요약 → 사건 추출 → 챕터 메타 요약."""
    paragraph_summaries: list[str] = []
    for text in blocks:
        t = (text or "").strip()
        if not t:
            paragraph_summaries.append("")
            continue
        summ = await llm.complete_chat(
            paragraph_summary_system(paragraph_max_chars),
            t,
            temperature=0.2,
        )
        paragraph_summaries.append(summ.strip())

    event_source = "\n\n".join(s for s in paragraph_summaries if s).strip()
    if not event_source:
        event_source = "\n\n".join((x or "").strip() for x in blocks if (x or "").strip())
    event_rows: list[dict[str, Any]] = []
    if event_source:
        events_raw = await llm.complete_chat(
            event_extract_system(),
            event_extract_user(event_source),
            temperature=0.15,
        )
        event_rows = _extract_json_array(events_raw)

    event_blob = "\n".join(
        f"- {idx + 1}. {row.get('title', '사건')} | 원인: {row.get('cause', '')} | 결과: {row.get('outcome', '')}"
        for idx, row in enumerate(event_rows)
    )
    joined_ps = "\n".join(s for s in paragraph_summaries if s)
    chapter_summary = await llm.complete_chat(
        chapter_summary_system(chapter_max_chars),
        event_blob or (joined_ps or event_source),
        temperature=0.2,
    )
    return {
        "paragraph_summaries": paragraph_summaries,
        "events": event_rows,
        "chapter_summary": chapter_summary.strip(),
    }


async def rollup_story_work_summary(
    session: AsyncSession,
    story_id: uuid.UUID,
    max_chars: int = 1200,
) -> None:
    """모든 챕터 요약을 모아 stories.work_summary 갱신."""
    r = await session.execute(
        select(Story).where(Story.id == story_id).options(selectinload(Story.episodes))
    )
    st = r.scalar_one_or_none()
    if not st:
        return
    eps = sorted(st.episodes, key=lambda e: e.chapter_num)
    lines: list[str] = []
    for e in eps:
        summ = (e.summary or "").strip()
        if summ:
            lines.append(f"챕터 {e.chapter_num}:\n{summ}")
    if not lines:
        st.work_summary = None
        return
    blob = "\n\n".join(lines)
    txt = await llm.complete_chat(
        work_summary_rollup_system(max_chars),
        work_summary_rollup_user(blob),
        temperature=0.25,
    )
    st.work_summary = (txt or "").strip()[:8000] or None
