"""
챕터 이벤트(`chapter_events`) ↔ 문단 청크(paragraph chunk) 매핑 헬퍼.

Parent-Child 기억 계층에서 paragraph → event → chapter 를 연결하기 위해
- finalize-episode 시 chunk_meta 에 `parent_event_id`/`parent_event_title` 을 기록한다.
- /event-map 엔드포인트에서 event 별로 실제 매핑된 paragraph refs 를 재계산한다.

한국어·영문 혼용을 고려해 공백/구두점 분리 + 길이 ≥ 2 토큰만으로 Jaccard-like 점수를 계산한다.
"""

from __future__ import annotations

import re
from typing import Any

_SPLIT_RE = re.compile(r"[\s,.!?;:\"'()\[\]{}/\\|<>·…\-–—_~`·]+")


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    toks = [t.strip().lower() for t in _SPLIT_RE.split(text) if t and t.strip()]
    return {t for t in toks if len(t) >= 2}


def event_id(idx: int) -> str:
    """챕터 내 이벤트 ID (1-indexed)."""
    return f"ev_{idx + 1}"


def event_token_bag(ev: dict[str, Any]) -> set[str]:
    toks: set[str] = set()
    for key in ("title", "cause", "outcome", "turning_point", "stakes"):
        toks |= _tokenize(str(ev.get(key) or ""))
    actors = ev.get("actors")
    if isinstance(actors, list):
        for a in actors:
            toks |= _tokenize(str(a or ""))
    return toks


def match_paragraph_to_event(
    paragraph: str,
    events: list[dict[str, Any]] | None,
    *,
    threshold: float = 0.02,
) -> tuple[str, str] | None:
    """문단을 가장 잘 설명하는 이벤트 하나를 찾는다. (event_id, title) 또는 None."""
    if not events:
        return None
    ptoks = _tokenize(paragraph)
    if not ptoks:
        return None
    best: tuple[str, str] | None = None
    best_score = 0.0
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        etoks = event_token_bag(ev)
        if not etoks:
            continue
        inter = ptoks & etoks
        if not inter:
            continue
        # 단락·이벤트 양쪽에서의 가중 평균
        score = (len(inter) / (len(etoks) ** 0.5 + 1e-6)) * (len(inter) / max(1, len(ptoks)))
        if score > best_score:
            title = str(ev.get("title") or f"사건 {idx + 1}").strip() or f"사건 {idx + 1}"
            best = (event_id(idx), title)
            best_score = score
    return best if best_score >= threshold else None


def build_event_map(
    events: list[dict[str, Any]] | None,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """이벤트별로 소속된 chunk refs 를 모아 반환.

    chunks: [{id, segment_index, paragraph_index, snippet, score?, parent_event_id?}]
    """
    out: list[dict[str, Any]] = []
    events = events or []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        eid = event_id(idx)
        refs = [c for c in chunks if (c.get("parent_event_id") == eid)]
        out.append(
            {
                "event_id": eid,
                "title": str(ev.get("title") or f"사건 {idx + 1}").strip() or f"사건 {idx + 1}",
                "cause": str(ev.get("cause") or "").strip(),
                "outcome": str(ev.get("outcome") or "").strip(),
                "turning_point": str(ev.get("turning_point") or "").strip(),
                "stakes": str(ev.get("stakes") or "").strip(),
                "ref_count": len(refs),
                "refs": refs,
            }
        )
    return out


def heatmap_bucket_from_score(score: float | None) -> int:
    """RAG 점수(0~1, 코사인 유사도)를 1~5 버킷으로 양자화. score None 이면 1."""
    if score is None:
        return 1
    try:
        s = float(score)
    except (TypeError, ValueError):
        return 1
    if s <= 0:
        return 1
    if s < 0.35:
        return 1
    if s < 0.55:
        return 2
    if s < 0.70:
        return 3
    if s < 0.85:
        return 4
    return 5
