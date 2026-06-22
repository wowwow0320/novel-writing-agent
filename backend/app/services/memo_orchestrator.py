"""작가 메모 → 서사 세그먼트 오케스트(1 LLM). expand-draft 의 순차 다블록 초안용."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.schemas import MemoQaAnswerItem, MemoQaQuestionItem, MemoSurveySnapshot
from app.services import llm

from app.config import get_settings
from app.services.json_extract import parse_llm_json_array, parse_llm_json_object
from app.services.prompts import (
    memo_orchestrator_system,
    memo_orchestrator_user,
    memo_qa_combined_system,
    memo_qa_combined_user,
)

logger = logging.getLogger(__name__)


@dataclass
class MemoSegment:
    id: str
    order: int
    label: str
    writer_memo: str


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _coerce(item: dict[str, Any], fallback_id: str) -> MemoSegment | None:
    try:
        sid = str(item.get("id", "")).strip() or fallback_id
        try:
            order = int(item.get("order", 0) or 0)
        except (TypeError, ValueError):
            order = 0
        label = str(item.get("label", "")).strip() or sid
        writer_memo = str(item.get("writer_memo", "")).strip()
        if not writer_memo:
            return None
        if order < 1:
            order = 1
        return MemoSegment(id=sid, order=order, label=label, writer_memo=writer_memo)
    except (TypeError, ValueError):
        return None


def _dedupe_sort(segments: list[MemoSegment]) -> list[MemoSegment]:
    seen: set[str] = set()
    out: list[MemoSegment] = []
    for i, s in enumerate(segments, start=1):
        sid = s.id or f"m{i}"
        if sid in seen:
            sid = f"m{i}"
        seen.add(sid)
        if s.id != sid:
            s = MemoSegment(id=sid, order=s.order, label=s.label, writer_memo=s.writer_memo)
        out.append(s)
    return sorted(out, key=lambda x: (x.order, x.id))


def tail_for_prompt(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return "…(앞부분 생략)\n" + t[-max_chars:]


def _clamp_float(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


def assess_memo_readiness(
    raw_memory: str,
    segments: list[MemoSegment],
    questions: list[MemoQaQuestionItem],
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Q&A 모달이 실제로 필요한지 판단하는 저비용 휴리스틱."""

    score = 0.92
    reasons: list[str] = []
    raw_len = len((raw_memory or "").strip())
    seg_count = max(1, len(segments))
    q_count = len(questions)
    mode = str((decision or {}).get("mode") or "")

    if mode == "multi_step":
        score -= 0.06
        reasons.append("입력 메모가 여러 본문 블록으로 분할될 가능성이 높습니다.")
    if seg_count > 1:
        score -= min(0.16, 0.04 * (seg_count - 1))
        reasons.append(f"세그먼트 {seg_count}개를 순차 생성해야 합니다.")
    if q_count > 0:
        score -= min(0.36, 0.08 * q_count)
        reasons.append(f"초안 전에 확인하면 좋은 질문 {q_count}개가 있습니다.")
    if q_count > 0 and raw_len < 180:
        score -= 0.12
        reasons.append("작가 메모가 짧아 동기·전환·감정선이 부족할 수 있습니다.")

    short_segments = sum(1 for seg in segments if len((seg.writer_memo or "").strip()) < 90)
    if q_count > 0 and short_segments:
        score -= min(0.16, 0.05 * short_segments)
        reasons.append(f"구체성이 낮은 세그먼트 {short_segments}개가 있습니다.")

    score = round(_clamp_float(score, 0.05, 0.98), 2)
    needs_questions = bool(questions) and score < 0.82
    if not reasons:
        reasons = ["입력 메모가 바로 생성 가능한 수준입니다."]

    return {
        "score": score,
        "needs_questions": needs_questions,
        "reasons": reasons,
    }


def estimate_memo_work(segments: list[MemoSegment]) -> dict[str, int]:
    """memo-qa-survey 결과를 재사용할 때 예상되는 실제 생성 비용."""

    count = max(1, len(segments))
    return {
        "segments": count,
        "draft_calls": count,
        "memory_searches": count,
        "stitch_calls": 1 if count > 1 else 0,
    }


async def orchestrate_memo_segments(
    ctx: dict[str, Any],
    raw_memory: str,
    max_segments: int,
    style_axes: dict[str, str] | None = None,
) -> list[MemoSegment]:
    pin = (ctx.get("pin") or "").strip()
    max_segments = _clamp(int(max_segments or 8), 1, 16)
    style_axes_json = json.dumps(style_axes, ensure_ascii=False) if style_axes else "(없음)"
    system = memo_orchestrator_system(max_segments)
    user = memo_orchestrator_user(pin, raw_memory or "", style_axes_json, max_segments)
    raw = await llm.complete_chat(system, user, temperature=0.3)
    try:
        items = parse_llm_json_array(raw)
    except ValueError as e:
        logger.warning("orchestrate_memo_segments JSON 파싱 실패: %s · %r", e, raw[:200])
        raise

    segments: list[MemoSegment] = []
    for i, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            continue
        s = _coerce(it, f"m{i}")
        if s is not None:
            segments.append(s)
    if not segments:
        raise ValueError("memo_orchestrate 응답이 비어 있거나 writer_memo 가 없습니다.")
    segments = _dedupe_sort(segments)
    return segments[:max_segments]


def _options_clamp(options: list[Any], qid: str) -> list[str] | None:
    out = [str(x).strip() for x in (options or []) if str(x).strip()]
    if len(out) < 2:
        logger.warning("질문 %s 보기 < 2개, 스킵", qid)
        return None
    if len(out) > 5:
        out = out[:5]
    return out


def _parse_survey_root(root: dict[str, Any], max_seg: int, max_q: int) -> tuple[list[MemoSegment], list[MemoQaQuestionItem]]:
    seg_in = root.get("segments")
    if not isinstance(seg_in, list):
        raise ValueError("segments 는 배열이어야 합니다")
    max_seg = _clamp(int(max_seg or 8), 1, 16)
    max_q = _clamp(int(max_q or 10), 0, 20)
    raw_segs: list[MemoSegment] = []
    for i, it in enumerate(seg_in, start=1):
        if not isinstance(it, dict):
            continue
        s = _coerce(it, f"m{i}")
        if s is not None:
            raw_segs.append(s)
    if not raw_segs:
        raise ValueError("segments 가 비어 있습니다")
    segments = _dedupe_sort(raw_segs)[:max_seg]
    seg_ids = {s.id for s in segments}

    qin = root.get("questions")
    questions: list[MemoQaQuestionItem] = []
    if isinstance(qin, list):
        for j, it in enumerate(qin[:max_q]):
            if not isinstance(it, dict):
                continue
            qid = str(it.get("id", "") or f"q{j+1}").strip() or f"q{j+1}"
            seg_ref = it.get("segment_id")
            seg_s: str | None
            if seg_ref is None or (isinstance(seg_ref, str) and not seg_ref.strip()):
                seg_s = None
            else:
                seg_s = str(seg_ref).strip()
                if seg_s and seg_s not in seg_ids:
                    raise ValueError(f"질문 {qid!r} 의 segment_id 가 세그 id 와 맞지 않습니다")
            qu = str(it.get("question", "") or "").strip()
            if not qu:
                continue
            opts = _options_clamp(it.get("options") or [], qid)
            if opts is None:
                continue
            fh = it.get("freeform_hint")
            hint = str(fh).strip() if fh is not None else None
            if hint is not None and not hint:
                hint = None
            questions.append(
                MemoQaQuestionItem(
                    id=qid,
                    segment_id=seg_s,
                    question=qu,
                    options=opts,
                    freeform_hint=hint,
                )
            )
    return segments, questions


async def run_memo_qa_survey(
    ctx: dict[str, Any],
    raw_memory: str,
    style_axes: dict[str, str] | None = None,
) -> tuple[list[MemoSegment], list[MemoQaQuestionItem]]:
    s = get_settings()
    max_seg = s.expand_orchestrator_max_segments
    max_q = s.memo_qa_max_questions
    pin = (ctx.get("pin") or "").strip()
    style_axes_json = json.dumps(style_axes, ensure_ascii=False) if style_axes else "(없음)"
    system = memo_qa_combined_system(max_seg, max_q)
    user = memo_qa_combined_user(pin, raw_memory or "", style_axes_json, max_seg, max_q)
    raw = await llm.complete_chat(system, user, temperature=0.35)
    try:
        root = parse_llm_json_object(raw)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("run_memo_qa_survey JSON 실패: %s · %r", e, raw[:200])
        raise ValueError("설문 JSON 파싱에 실패했습니다") from e
    if not isinstance(root, dict):
        raise ValueError("최상위 JSON 이 객체가 아닙니다")
    return _parse_survey_root(root, max_seg, max_q)


def apply_memo_qa_answers(
    survey: MemoSurveySnapshot,
    answers: dict[str, MemoQaAnswerItem] | None,
) -> list[MemoSegment]:
    s = get_settings()
    fmax = s.memo_qa_max_freeform_chars
    seg_by_id: dict[str, MemoSegment] = {
        s.id: MemoSegment(id=s.id, order=s.order, label=s.label, writer_memo=(s.writer_memo or "").strip()) for s in survey.segments
    }
    if not seg_by_id:
        raise ValueError("세그먼트가 없습니다")
    first_id = sorted(survey.segments, key=lambda x: (x.order, x.id))[0].id

    bufs: dict[str, str] = {i: w.writer_memo for i, w in seg_by_id.items()}

    for q in survey.questions:
        a = (answers or {}).get(q.id)
        idx = int(a.selected_index) if a else 0
        freeform = (a.freeform if a else "") or ""
        freeform = (freeform or "")[:fmax]
        if not q.options or idx < 0 or idx >= len(q.options):
            raise ValueError(f"질문 {q.id!r} 의 selected_index 가 보기 범위를 벗어났습니다")
        chosen = q.options[idx]
        line = f"\n\n[작가 응답 — {q.question}]\n선택: {chosen}\n직접 메모: {freeform or '(없음)'}\n"
        if q.segment_id is None or str(q.segment_id).strip() == "":
            tid = first_id
        else:
            tid = str(q.segment_id).strip()
            if tid not in bufs:
                raise ValueError(f"질문 {q.id!r} 의 segment_id 가 유효하지 않습니다")
        bufs[tid] = (bufs.get(tid, "")).rstrip() + line

    out: list[MemoSegment] = []
    for s in survey.segments:
        wid = s.id
        if wid not in bufs:
            continue
        out.append(
            MemoSegment(
                id=wid,
                order=s.order,
                label=s.label,
                writer_memo=bufs[wid].strip(),
            )
        )
    return _dedupe_sort(out)
