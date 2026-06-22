"""Scene Planner & Writer & Stitcher (Module 02).

docs/pipeline/02_ROUTER_GENERATION.md §4.1 참조.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.schemas import ScenePlanItem
from app.services import llm
from app.services.json_extract import parse_llm_json_array
from app.services.prompts import (
    scene_plan_system,
    scene_plan_user,
    scene_writer_system,
    scene_writer_user,
)

logger = logging.getLogger(__name__)

_ALLOWED_BEATS = {"기", "승", "전", "결", "보조", "회상", "에필로그"}
_ALLOWED_POV = {"1st", "3rd_limited", "3rd_omniscient", "2nd", "mixed"}
_ALLOWED_TENSION = {"low", "mid", "high", "climax"}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _coerce_scene(item: dict[str, Any], fallback_id: str) -> ScenePlanItem | None:
    try:
        sid = str(item.get("id", "")).strip() or fallback_id
        beat_raw = str(item.get("beat", "기")).strip()
        beat = beat_raw if beat_raw in _ALLOWED_BEATS else "기"
        pov_raw = str(item.get("pov", "3rd_limited")).strip()
        pov = pov_raw if pov_raw in _ALLOWED_POV else "3rd_limited"
        tension_raw = str(item.get("tension", "mid")).strip().lower()
        tension = tension_raw if tension_raw in _ALLOWED_TENSION else "mid"
        goal = str(item.get("goal", "")).strip()
        hint = str(item.get("hint", "")).strip()
        try:
            approx = int(item.get("approx_chars", 600) or 600)
        except (TypeError, ValueError):
            approx = 600
        approx = _clamp(approx, 200, 2000)
        return ScenePlanItem(
            id=sid,
            beat=beat,  # type: ignore[arg-type]
            pov=pov,  # type: ignore[arg-type]
            goal=goal,
            tension=tension,  # type: ignore[arg-type]
            hint=hint,
            approx_chars=approx,
        )
    except (TypeError, ValueError):
        return None


def _dedupe_ids(scenes: list[ScenePlanItem]) -> list[ScenePlanItem]:
    seen: set[str] = set()
    out: list[ScenePlanItem] = []
    for i, s in enumerate(scenes, start=1):
        sid = s.id or f"s{i}"
        if sid in seen:
            sid = f"s{i}"
        seen.add(sid)
        if s.id != sid:
            s = s.model_copy(update={"id": sid})
        out.append(s)
    return out


async def plan_scenes(
    ctx: dict[str, Any],
    raw_memory: str,
    max_scenes: int = 6,
    style_axes: dict[str, str] | None = None,
) -> list[ScenePlanItem]:
    pin = (ctx.get("pin") or "").strip()
    max_scenes = _clamp(int(max_scenes or 6), 1, 12)
    style_axes_json = json.dumps(style_axes, ensure_ascii=False) if style_axes else "(없음)"
    system = scene_plan_system(max_scenes)
    user = scene_plan_user(pin, raw_memory or "", style_axes_json, max_scenes)
    raw = await llm.complete_chat(system, user, temperature=0.35)
    try:
        items = parse_llm_json_array(raw)
    except ValueError as e:
        logger.warning("plan_scenes JSON 파싱 실패: %s · 원문 앞 200자=%r", e, raw[:200])
        raise

    scenes: list[ScenePlanItem] = []
    for i, it in enumerate(items, start=1):
        s = _coerce_scene(it, f"s{i}")
        if s is not None:
            scenes.append(s)
    if not scenes:
        raise ValueError("scene_plan 응답이 비어 있거나 형식이 올바르지 않습니다.")
    scenes = _dedupe_ids(scenes)
    return scenes[:max_scenes]


def _tail(text: str, n: int = 800) -> str:
    t = (text or "").strip()
    return t[-n:] if len(t) > n else t


async def write_scene(
    ctx: dict[str, Any],
    scene: ScenePlanItem,
    prev_scene_tail: str,
    next_scene_head_hint: str,
    style_axes: dict[str, str] | None = None,
    genre_override: str | None = None,
    memory_block: str = "",
) -> str:
    pin = (ctx.get("pin") or "").strip()
    genre = (genre_override or ctx.get("genre") or "").strip()
    style_guide = str(ctx.get("style_guide") or "")
    role = llm.genre_writer_role(genre, style_guide, style_axes)
    system = scene_writer_system(pin, role, style_guide, str(ctx.get("language") or "KO"))
    user = scene_writer_user(
        scene_id=scene.id,
        beat=str(scene.beat),
        pov=str(scene.pov),
        tension=str(scene.tension),
        goal=scene.goal,
        hint=scene.hint,
        approx_chars=scene.approx_chars,
        prev_tail=_tail(prev_scene_tail, 800),
        next_head_hint=(next_scene_head_hint or "").strip()[:240],
        memory_block=memory_block,
    )
    return await llm.complete_chat(system, user, temperature=0.55)


_LEAD_SUMMARY_PAT = re.compile(
    r"^\s*(이번 (?:씬|장면)(?:은|에서)?|요약(?:하자면|하면)?|앞서.*?에서)[^\n]*\n",
    re.IGNORECASE,
)
_LABEL_LEAD_PAT = re.compile(r"^\s*(?:씬\s*\d+|scene\s*\d+|s\d+)\s*[:.\-)]\s*", re.IGNORECASE)


def _trim_scene(segment: str) -> str:
    t = (segment or "").strip()
    if not t:
        return ""
    t = _LABEL_LEAD_PAT.sub("", t)
    t = _LEAD_SUMMARY_PAT.sub("", t, count=1).lstrip()
    return t.rstrip()


def stitch_scenes(segments: list[str]) -> str:
    trimmed = [_trim_scene(s) for s in segments if (s or "").strip()]
    if not trimmed:
        return ""
    out: list[str] = []
    for seg in trimmed:
        if out and out[-1].strip()[-120:] == seg.strip()[:120] and len(seg) > 120:
            seg = seg[120:]
        out.append(seg)
    merged = "\n\n".join(out)
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
    return merged


async def stitch_with_llm(
    segments: list[str],
    ctx: dict[str, Any],
    source_memo: str = "",
) -> str:
    draft = stitch_scenes(segments)
    if not draft.strip() or len(segments) <= 1:
        return draft
    source_memo = (source_memo or "").strip()
    memo_rule = (
        "\n- [원본 작가 메모]가 있으면, 최종 본문은 그 메모의 장소, 시간, 인물, 수량, 대사, 감정, 사건 순서를 따라야 합니다."
        "\n- 초안이 원본 메모와 충돌하면 원본 메모가 맞습니다. 누락된 핵심 사건은 복원하고, 새로 생긴 엉뚱한 사건은 제거합니다."
        if source_memo
        else ""
    )
    system = f"""{(ctx.get("pin") or "").strip()}

당신은 장편 소설 회차 통합 편집자입니다.
여러 세그먼트로 생성된 초안을 하나의 자연스러운 회차 본문으로 다듬습니다.

규칙:
- 사건, 대사, 정보는 삭제하지 말고 보존합니다.
- 초안이 아니라 원본 작가 메모가 최종 사실 기준입니다.
- 세그먼트마다 반복된 장소·인물·상황 설명을 제거합니다.
- 장면 전환이 필요한 곳만 짧게 보강합니다.
- POV와 시제를 통일합니다.
- 원본 메모에 없는 배경/관계/목표로 본문을 바꾸지 않습니다.{memo_rule}
- 전체 소설의 기승전결을 현재 챕터 안에서 닫으려 하지 않습니다. 원본 메모가 멈춘 곳에서 자연스럽게 멈춥니다.
- "나는/내가/난"으로 시작하는 문장이 반복되면 주어 생략, 감각 묘사, 행동 묘사로 문장 구조를 바꿉니다.
- 출력은 오직 최종 소설 본문만 반환합니다."""
    source_block = f"""[원본 작가 메모]
{source_memo}

""" if source_memo else ""
    user = f"""{source_block}[세그먼트 초안]
{draft}

[수정 목표]
위 초안을 한 회차처럼 자연스럽게 이어지도록 통합하되, 원본 작가 메모의 구체 사건과 정보는 반드시 보존하세요.
원본에 없는 새 사건은 제거하고, 반복되는 "나는/내가/난" 문장은 자연스럽게 줄이세요."""
    try:
        revised = await llm.complete_chat(system, user, temperature=0.25)
    except Exception as exc:
        logger.warning("LLM stitch 실패, 규칙 기반 stitch 사용: %s", exc)
        return draft
    return (revised or draft).strip()


def build_neighbors(
    scenes: list[ScenePlanItem],
    contents: dict[str, str],
    current_index: int,
) -> tuple[str, str]:
    prev_tail = ""
    if current_index > 0:
        prev_id = scenes[current_index - 1].id
        prev_tail = _tail(contents.get(prev_id, ""), 800)
    next_hint = ""
    if current_index + 1 < len(scenes):
        nxt = scenes[current_index + 1]
        parts = [nxt.goal or "", nxt.hint or ""]
        next_hint = " / ".join(p.strip() for p in parts if p.strip())[:240]
    return prev_tail, next_hint
