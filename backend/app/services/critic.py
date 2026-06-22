"""Module 03 — Critic / Review (수동 트리거).

- `detect_pov` : 본문의 시점(인칭)·시제를 LLM 으로 판정.
- `run_episode_review` : 직전 본문·Top-K·챕터 흐름·Critic LLM 을 하나로 묶어
  `EpisodeReviewResponse` 페이로드를 만든다.
- `ExceptionRouter` 역할은 meta_tags 기반 `allowed_bypasses` 와 Critic 프롬프트 지시로 처리.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Episode
from app.services import llm
from app.services.context_builder import build_writer_context
from app.services.episode_text import full_episode_writing_text
from app.services.prompts import critic_system, critic_user, pov_detect_system, pov_detect_user
from app.services.story_pipeline import _extract_json_object, bridge_continuity_bundle

logger = logging.getLogger(__name__)


_VALID_POV = {"1st", "3rd_limited", "3rd_omniscient", "2nd", "mixed", "unknown"}
_VALID_TENSE = {"past", "present", "mixed", "unknown"}
_VALID_SEVERITY = {"info", "warn", "error"}
_VALID_CATEGORY = {"continuity", "pov", "logic", "bible", "chapter_flow", "style"}


def _previous_episode_text(session_episodes: list[Episode], current_chapter: int) -> str:
    prev = [e for e in session_episodes if e.chapter_num == current_chapter - 1]
    if not prev:
        return ""
    return (full_episode_writing_text(prev[0]) or prev[0].raw_memory or "").strip()


async def detect_pov(pin: str, text: str) -> dict[str, Any]:
    """시점/시제 판정. LLM 실패 시 unknown 폴백."""
    body = (text or "").strip()
    if not body:
        return {
            "pov": "unknown",
            "tense": "unknown",
            "confidence": 0.0,
            "rationale": "본문이 비어 있음",
        }
    try:
        raw = await llm.complete_chat(
            pov_detect_system(pin),
            pov_detect_user(body),
            temperature=0.0,
        )
        parsed = _extract_json_object(raw)
    except (ValueError, RuntimeError) as e:
        logger.warning("detect_pov LLM 실패: %s", e)
        return {
            "pov": "unknown",
            "tense": "unknown",
            "confidence": 0.0,
            "rationale": "LLM 실패(heuristic 미적용)",
        }
    pov = str(parsed.get("pov", "unknown")).strip()
    tense = str(parsed.get("tense", "unknown")).strip()
    if pov not in _VALID_POV:
        pov = "unknown"
    if tense not in _VALID_TENSE:
        tense = "unknown"
    try:
        conf = float(parsed.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    rationale = str(parsed.get("rationale", "")).strip()[:400]
    return {"pov": pov, "tense": tense, "confidence": conf, "rationale": rationale}


def _compute_allowed_bypasses(meta_tags: dict[str, Any] | None) -> list[str]:
    if not isinstance(meta_tags, dict):
        return []
    out: list[str] = []
    if bool(meta_tags.get("allow_discontinuity")):
        out.append("continuity")
    if bool(meta_tags.get("omnibus")):
        out.append("continuity")
    if bool(meta_tags.get("time_jump")):
        out.append("chapter_flow")
    return sorted(set(out))


def _apply_bypass(issues: list[dict[str, Any]], allowed: list[str]) -> list[dict[str, Any]]:
    if not allowed:
        return issues
    allowed_set = set(allowed)
    applied: list[dict[str, Any]] = []
    for it in issues:
        cat = str(it.get("category", "continuity"))
        if cat in allowed_set:
            it = dict(it)
            it["bypassed"] = True
            it["bypass_reason"] = f"meta_tags 에 의해 우회(카테고리: {cat})"
        applied.append(it)
    return applied


def _top_k_blob(hits: list[dict[str, Any]], max_chars: int = 2000) -> str:
    lines: list[str] = []
    total = 0
    for h in hits:
        eid = h.get("episode_id") or "?"
        chnum = h.get("chapter_num") or "?"
        snip = (h.get("snippet") or "").strip().replace("\n", " ")
        if len(snip) > 360:
            snip = snip[:360] + "…"
        line = f"- ep={eid} (ch {chnum}): {snip}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


async def _critic_call(
    pin: str,
    allowed_bypasses: list[str],
    previous_text: str,
    current_text: str,
    bible_block: str,
    top_k_hits: list[dict[str, Any]],
    chapter_summary: str,
    chapter_events_blob: str,
) -> tuple[list[dict[str, Any]], str]:
    """Critic LLM 호출. JSON 파싱 실패 시 빈 이슈 + 에러 메시지."""
    top_k_blob = _top_k_blob(top_k_hits)
    try:
        raw = await llm.complete_chat(
            critic_system(pin),
            critic_user(
                allowed_bypasses=allowed_bypasses,
                previous_excerpt=previous_text[-3500:] if previous_text else "",
                current_text=current_text,
                bible_block=bible_block,
                top_k_blob=top_k_blob,
                chapter_summary=chapter_summary,
                chapter_events_blob=chapter_events_blob,
            ),
            temperature=0.15,
        )
        parsed = _extract_json_object(raw)
    except (ValueError, RuntimeError) as e:
        logger.warning("critic LLM 실패: %s", e)
        return [], f"LLM 검수 실패: {e}"
    issues_raw = parsed.get("issues")
    issues: list[dict[str, Any]] = []
    if isinstance(issues_raw, list):
        for i, it in enumerate(issues_raw):
            if not isinstance(it, dict):
                continue
            sev = str(it.get("severity", "warn")).strip().lower()
            if sev not in _VALID_SEVERITY:
                sev = "warn"
            cat = str(it.get("category", "continuity")).strip().lower()
            if cat not in _VALID_CATEGORY:
                cat = "continuity"
            issues.append(
                {
                    "id": f"llm-{i+1}",
                    "severity": sev,
                    "category": cat,
                    "message": str(it.get("message", "")).strip()[:800] or "(메시지 없음)",
                    "evidence": str(it.get("evidence", "")).strip()[:600] or None,
                    "suggestion": str(it.get("suggestion", "")).strip()[:600] or None,
                    "bypassed": False,
                    "bypass_reason": None,
                }
            )
    summary = str(parsed.get("summary", "")).strip()[:1000]
    return issues, summary


def _logic_to_issues(logic: dict[str, Any]) -> list[dict[str, Any]]:
    """규칙 기반 logic_consistency_harness 결과를 이슈 카드로 변환."""
    out: list[dict[str, Any]] = []
    raw = logic.get("issues") if isinstance(logic, dict) else None
    if not isinstance(raw, list):
        return out
    for i, txt in enumerate(raw):
        if not isinstance(txt, str) or not txt.strip():
            continue
        out.append(
            {
                "id": f"logic-{i+1}",
                "severity": "warn",
                "category": "logic",
                "message": txt.strip()[:400],
                "evidence": None,
                "suggestion": None,
                "bypassed": False,
                "bypass_reason": None,
            }
        )
    return out


async def run_episode_review(
    session: AsyncSession,
    episode_id: uuid.UUID,
    *,
    top_k: int = 6,
    include_pov: bool = True,
    include_critic: bool = True,
    allow_discontinuity_override: bool | None = None,
) -> dict[str, Any]:
    """수동 버튼으로 호출되는 메인 진입점.

    진행 순서:
    1) 컨텍스트(build_writer_context) 로드 → pin / bible_block / prev_summary.
    2) 직전 본문 확보(이전 챕터 전문).
    3) `bridge_continuity_bundle` 로 규칙 검사 + Top-K + chapter_flow_note.
    4) `detect_pov` 로 본문 POV 판정.
    5) `_critic_call` 로 LLM issues 수집 + 규칙 이슈 병합 + meta_tags 기반 bypass.
    """
    r = await session.execute(
        select(Episode)
        .where(Episode.id == episode_id)
        .options(selectinload(Episode.bodies))
    )
    ep = r.scalar_one_or_none()
    if not ep:
        raise ValueError("episode not found")

    ctx = await build_writer_context(session, ep.story_id, ep.chapter_num)
    pin: str = ctx.get("pin", "")
    bible_block: str = ctx.get("bible_block", "")
    prev_summary: str = ctx.get("prev_summary", "")

    current_text = (full_episode_writing_text(ep) or ep.raw_memory or "").strip()
    if not current_text:
        raise ValueError("본문이 비어 있어 검수할 내용이 없습니다")

    # 이전 챕터 전문(있으면) 확보 — bodies 필요
    r2 = await session.execute(
        select(Episode)
        .where(Episode.story_id == ep.story_id)
        .options(selectinload(Episode.bodies))
    )
    all_eps = list(r2.scalars().all())
    previous_text = _previous_episode_text(all_eps, ep.chapter_num)

    ep_meta = ep.meta_tags if isinstance(ep.meta_tags, dict) else {}
    effective_meta = dict(ep_meta)
    if allow_discontinuity_override is not None:
        effective_meta["allow_discontinuity"] = bool(allow_discontinuity_override)
    allow_discontinuity = bool(effective_meta.get("allow_discontinuity", False))
    allowed_bypasses = _compute_allowed_bypasses(effective_meta)

    # 3) 규칙/Top-K/챕터 흐름 bundle
    import json as _json

    bundle = await bridge_continuity_bundle(
        session,
        ep.story_id,
        previous_text,
        current_text,
        chapter_summary=ep.summary or "",
        chapter_events_blob=_json.dumps(ep.chapter_events, ensure_ascii=False)
        if isinstance(ep.chapter_events, list)
        else None,
        allow_discontinuity=allow_discontinuity,
        top_k=top_k,
    )
    logic = bundle.get("logic") or {}
    top_k_hits = bundle.get("top_k_hits") or []
    chapter_flow_note = bundle.get("chapter_flow_note")

    # 4) POV 판정
    pov_payload: dict[str, Any] | None = None
    if include_pov:
        pov_payload = await detect_pov(pin, current_text)

    # 5) LLM Critic
    llm_issues: list[dict[str, Any]] = []
    summary_note = ""
    if include_critic:
        llm_issues, summary_note = await _critic_call(
            pin,
            allowed_bypasses,
            previous_text,
            current_text,
            bible_block,
            top_k_hits,
            ep.summary or "",
            _json.dumps(ep.chapter_events, ensure_ascii=False)
            if isinstance(ep.chapter_events, list)
            else "",
        )

    # POV 불일치 이슈 자동 추가(명시 meta_tags 와 감지 결과가 다르면)
    declared_pov = str(effective_meta.get("pov", "")).strip() or None
    declared_tense = str(effective_meta.get("tense", "")).strip() or None
    pov_auto_issues: list[dict[str, Any]] = []
    if pov_payload:
        if declared_pov and declared_pov != pov_payload["pov"] and pov_payload["pov"] != "unknown":
            pov_auto_issues.append(
                {
                    "id": "pov-declared-mismatch",
                    "severity": "warn",
                    "category": "pov",
                    "message": (
                        f"선언된 시점({declared_pov})과 감지된 시점({pov_payload['pov']})이 다릅니다"
                    ),
                    "evidence": pov_payload.get("rationale") or None,
                    "suggestion": "챕터 meta_tags 또는 본문 시점을 통일하세요",
                    "bypassed": False,
                    "bypass_reason": None,
                }
            )
        if (
            declared_tense
            and declared_tense != pov_payload["tense"]
            and pov_payload["tense"] != "unknown"
        ):
            pov_auto_issues.append(
                {
                    "id": "tense-declared-mismatch",
                    "severity": "info",
                    "category": "pov",
                    "message": (
                        f"선언된 시제({declared_tense})와 감지된 시제({pov_payload['tense']})가 다릅니다"
                    ),
                    "evidence": pov_payload.get("rationale") or None,
                    "suggestion": None,
                    "bypassed": False,
                    "bypass_reason": None,
                }
            )

    rule_issues = _logic_to_issues(logic)
    all_issues = rule_issues + pov_auto_issues + llm_issues
    all_issues = _apply_bypass(all_issues, allowed_bypasses)

    return {
        "episode_id": ep.id,
        "issues": all_issues,
        "pov": pov_payload,
        "logic": logic,
        "top_k_hits": top_k_hits,
        "chapter_flow_note": chapter_flow_note,
        "allowed_bypasses": allowed_bypasses,
        "meta_tags": effective_meta,
        "summary_note": summary_note,
    }
