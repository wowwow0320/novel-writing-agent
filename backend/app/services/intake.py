"""Intake & Context — Analyzer + QuestionLoop 인터랙티브 모듈(Module 01).

docs/pipeline/01_INTAKE_CONTEXT.md §4 참조.

서버는 상태를 저장하지 않는다. 클라이언트가 `IntakeState` 스냅샷을 들고
매 요청에 통째로 재전송하는 방식(stateless)이다. finalize 시점에만
`Story.world_setting`·`Story.global_rules`·`StoryBibleEntry` 에 write.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Story
from app.schemas import IntakeAnswerEntry, IntakeState
from app.services.foundation_memory import sync_foundation_memory
from app.services.story_pipeline import (
    classify_required_elements,
    extract_foundation,
)

logger = logging.getLogger(__name__)

MAX_ANSWERS = 20

def merge_answers_into_input(state: IntakeState) -> str:
    """story_input 에 answers 를 Q/A 포맷으로 append 한다."""
    base = (state.story_input or "").strip()
    if not state.answers:
        return base
    parts = [base] if base else []
    parts.append("[보강 질문·답]")
    for entry in state.answers:
        q = (entry.q or "").strip()
        a = (entry.a or "").strip()
        if not a:
            continue
        parts.append(f"- Q: {q}\n  A: {a}")
    return "\n".join(parts).strip()


async def intake_run_once(state: IntakeState) -> IntakeState:
    """state 기반으로 Analyzer + QuestionLoop 를 한 번 실행해 갱신된 state 를 돌려준다."""
    composed = merge_answers_into_input(state)
    if not composed:
        return IntakeState(
            story_input=state.story_input,
            extracted={},
            question_check={
                "who": {"present": False, "reason": "(입력 비어 있음)"},
                "where": {"present": False, "reason": "(입력 비어 있음)"},
                "what": {"present": False, "reason": "(입력 비어 있음)"},
                "missing": ["who", "where", "what"],
                "named_entities": {"characters": [], "places": []},
                "missing_names": [],
                "suggested_questions": [],
            },
            answers=list(state.answers),
            iteration=state.iteration + 1,
        )

    extracted, question_check = await asyncio.gather(
        extract_foundation(composed),
        classify_required_elements(composed),
    )
    return IntakeState(
        story_input=state.story_input,
        extracted=extracted,
        question_check=question_check,
        answers=list(state.answers),
        iteration=state.iteration + 1,
    )


def append_answer(state: IntakeState, q: str, a: str) -> IntakeState:
    """state.answers 에 (q, a) 한 쌍을 append. 최대 MAX_ANSWERS 개로 캡."""
    answers = list(state.answers)
    q_clean = (q or "").strip()
    a_clean = (a or "").strip()
    if a_clean:
        answers.append(
            IntakeAnswerEntry(q=q_clean, a=a_clean, ts=datetime.now(timezone.utc).isoformat())
        )
    if len(answers) > MAX_ANSWERS:
        answers = answers[-MAX_ANSWERS:]
    return IntakeState(
        story_input=state.story_input,
        extracted=state.extracted,
        question_check=state.question_check,
        answers=answers,
        iteration=state.iteration,
    )


def _compact_world_text(state: IntakeState) -> str:
    """finalize 시 Story.world_setting 에 저장할 합성 텍스트."""
    merged = merge_answers_into_input(state)
    extracted = state.extracted if isinstance(state.extracted, dict) else {}
    premise = str(extracted.get("premise", "")).strip()
    parts: list[str] = []
    if premise:
        parts.append(f"[대전제]\n{premise}")
    if merged:
        parts.append(merged)
    return ("\n\n".join(parts)).strip()


def _global_rules_from_extracted(extracted: dict[str, Any], merge_into: dict[str, Any] | None) -> dict[str, Any]:
    """extracted 로부터 keywords/constraints 를 global_rules 에 병합."""
    base: dict[str, Any] = dict(merge_into) if isinstance(merge_into, dict) else {}
    kws = extracted.get("keywords") if isinstance(extracted, dict) else []
    if isinstance(kws, list) and kws:
        existing = base.get("keywords") if isinstance(base.get("keywords"), list) else []
        merged = list(dict.fromkeys([*existing, *[str(k).strip() for k in kws if str(k).strip()]]))
        base["keywords"] = merged
    backgrounds = (
        extracted.get("entities", {}).get("backgrounds")
        if isinstance(extracted, dict) and isinstance(extracted.get("entities"), dict)
        else []
    )
    constraints: list[str] = []
    if isinstance(backgrounds, list):
        for bg in backgrounds:
            if not isinstance(bg, dict):
                continue
            for c in bg.get("constraints", []) if isinstance(bg.get("constraints"), list) else []:
                cs = str(c).strip()
                if cs:
                    constraints.append(cs)
    if constraints:
        existing_c = base.get("constraints") if isinstance(base.get("constraints"), list) else []
        base["constraints"] = list(dict.fromkeys([*existing_c, *constraints]))
    return base


async def finalize_story_world(
    session: AsyncSession,
    story_id: uuid.UUID,
    state: IntakeState,
    merge_global_rules: bool = True,
) -> dict[str, Any]:
    """확정 단계. Story.world_setting + global_rules 저장 + bible seed."""
    story = await session.get(Story, story_id)
    if not story:
        raise ValueError("story not found")

    world_text = _compact_world_text(state)
    story.world_setting = world_text or None

    if merge_global_rules:
        story.global_rules = _global_rules_from_extracted(
            state.extracted if isinstance(state.extracted, dict) else {},
            story.global_rules if isinstance(story.global_rules, dict) else None,
        )
    await session.flush()

    foundation_sync: dict[str, Any] = {
        "bible": 0,
        "entities": 0,
        "events": 0,
        "relationships": 0,
        "summary_nodes": 0,
        "graph_sync": {"enabled": False},
    }
    if world_text:
        foundation_sync = await sync_foundation_memory(
            session,
            story_id,
            world_text,
            origin="intake_finalize",
        )

    return {
        "bible_seeded": int(foundation_sync.get("bible") or 0),
        "foundation_sync": foundation_sync,
        "world_setting_chars": len(world_text or ""),
        "global_rules_json": json.dumps(story.global_rules or {}, ensure_ascii=False),
    }
