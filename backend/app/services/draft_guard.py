"""Draft faithfulness guard for memoir-like longform generation.

The generator may still invent plausible plot beats even when prompts say not to.
This guard detects common drift cheaply, then asks the LLM to revise only when
there is evidence that the draft moved away from the writer memo.
"""

from __future__ import annotations

import re
from typing import Any

from app.services import llm


PLOT_ADVANCEMENT_TERMS = (
    "도서관",
    "약속",
    "사랑",
    "고백",
    "데이트",
    "연인",
    "우정에서 사랑",
    "관계가 우정에서 사랑",
    "함께 시간을 보내",
    "함께 공부",
    "한국어 연습",
    "한국어를 배우",
    "언어를 보완",
    "다음 날 수업",
    "발표를 준비",
    "자신감이 생기",
    "자신감을 주",
    "응원하는 듯한 눈빛",
    "칭찬했다",
    "끌리게 되",
    "좋아한다는 사실",
    "진심을 전",
)

COMMON_NOUNS = {
    "가득",
    "감정",
    "겉옷",
    "고정",
    "관계",
    "관념",
    "교실",
    "그녀",
    "기대",
    "긴장",
    "도서관",
    "마음",
    "만남",
    "머릿속",
    "미소",
    "발음",
    "본문",
    "불안",
    "사랑",
    "생활",
    "생각",
    "수업",
    "시간",
    "시작",
    "어학원",
    "영어",
    "외국",
    "우정",
    "자신감",
    "장면",
    "처음",
    "친구",
    "캐나다",
    "패딩",
    "화장실",
}

NAME_CANDIDATE_RE = re.compile(r"(?<![가-힣])([가-힣]{2,3})(?=(?:은|는|이|가|을|를|에게|와|과|의|도|랑|덕분에)\b)")
VOCATIVE_NAME_RE = re.compile(r"(?<![가-힣])([가-힣]{2,3})(?:아|야)(?=[,，.!?…\"'“”‘’\s])")
QUOTE_RE = re.compile(r'"([^"\n]{2,80})"')
FIRST_PERSON_START_RE = re.compile(r"(?:^|[.!?。]\s+)(나는|내가|난)\b")
MAJOR_ISSUE_KINDS = {"unmentioned_name", "unmentioned_dialogue", "unmentioned_plot_beat"}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _contains_loose(haystack: str, needle: str) -> bool:
    return _compact(needle) in _compact(haystack)


def _plain_source_memo(source_memo: str) -> str:
    text = (source_memo or "").strip()
    if "[세그먼트 메모]" in text:
        text = text.split("[세그먼트 메모]", 1)[1]
    elif "[원본 작가 메모]" in text:
        text = text.split("[원본 작가 메모]", 1)[1]
    for marker in ("[세그먼트 원석]",):
        if marker in text:
            text = text.split(marker, 1)[0]
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        lines.append(stripped)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned or (source_memo or "").strip()


def _has_major_issues(issues: list[dict[str, Any]]) -> bool:
    return any(str(i.get("kind")) in MAJOR_ISSUE_KINDS for i in issues)


def find_draft_drift_issues(source_memo: str, draft: str) -> list[dict[str, Any]]:
    """Return deterministic drift signals between writer memo and generated draft."""

    source = source_memo or ""
    text = draft or ""
    issues: list[dict[str, Any]] = []

    for term in PLOT_ADVANCEMENT_TERMS:
        if term in text and term not in source:
            issues.append(
                {
                    "kind": "unmentioned_plot_beat",
                    "value": term,
                    "message": f"원문에 없는 사건/관계 진전 표현: {term}",
                }
            )

    source_compact = _compact(source)
    for quote in QUOTE_RE.findall(text):
        q = quote.strip()
        if q and _compact(q) not in source_compact:
            issues.append(
                {
                    "kind": "unmentioned_dialogue",
                    "value": q,
                    "message": f"원문에 없는 직접 대사: {q}",
                }
            )

    names: list[str] = []
    for match in list(NAME_CANDIDATE_RE.finditer(text)) + list(VOCATIVE_NAME_RE.finditer(text)):
        name = match.group(1)
        if name in COMMON_NOUNS or name in names:
            continue
        if not _contains_loose(source, name):
            names.append(name)
    for name in names[:8]:
        issues.append(
            {
                "kind": "unmentioned_name",
                "value": name,
                "message": f"원문에 없는 고유명 후보: {name}",
            }
        )

    first_person_starts = FIRST_PERSON_START_RE.findall(text)
    if len(first_person_starts) >= 4:
        issues.append(
            {
                "kind": "repetitive_first_person",
                "value": len(first_person_starts),
                "message": f"'나는/내가/난' 문장 시작이 {len(first_person_starts)}회 반복됨",
            }
        )

    return issues


def memo_fidelity_revision_system() -> str:
    return """당신은 장편 소설 집필 보조 에디터입니다.
역할은 새 창작이 아니라, [초안]을 [작가 원문 메모]에 충실하게 되돌리는 것입니다.

규칙:
- 원문에 없는 이름, 장소 이동, 약속, 관계 진전, 사랑/고백, 격려 대사, 결말을 제거합니다.
- 원문의 사건 순서, 인물 인상, 대사, 감정, 정보량을 보존합니다.
- 전체 소설의 기승전결을 닫지 말고, 원문 메모가 멈춘 지점에서 멈춥니다.
- "나는/내가/난"으로 시작하는 문장이 반복되면 주어 생략과 문장 구조 변경으로 줄입니다.
- 문장은 소설답게 다듬되, 없는 사건을 새로 만들지 않습니다.
- 출력은 수정된 소설 본문만 반환합니다."""


def memo_fidelity_revision_user(source_memo: str, draft: str, issues: list[dict[str, Any]]) -> str:
    issue_lines = "\n".join(f"- {i['message']}" for i in issues[:12]) or "- 자동 감지 이슈 없음"
    return f"""[작가 원문 메모]
{source_memo}

[감지된 이탈]
{issue_lines}

[초안]
{draft}

[수정 요청]
초안을 원문 메모에 충실한 장면 확장으로 다시 다듬으세요."""


async def revise_draft_if_needed(source_memo: str, draft: str) -> tuple[str, dict[str, Any]]:
    issues = find_draft_drift_issues(source_memo, draft)
    trace: dict[str, Any] = {
        "issues": issues,
        "revision": "skipped",
    }
    if not issues:
        return draft, trace

    revised = await llm.complete_chat(
        memo_fidelity_revision_system(),
        memo_fidelity_revision_user(source_memo, draft, issues),
        temperature=0.2,
    )
    revised = (revised or draft).strip()
    trace["revision"] = "llm"
    post_issues = find_draft_drift_issues(source_memo, revised)
    trace["post_issues"] = post_issues
    if _has_major_issues(post_issues):
        fallback = _plain_source_memo(source_memo)
        trace["revision"] = "fallback_source_memo"
        trace["fallback_reason"] = "major_drift_after_revision"
        trace["fallback_issues"] = post_issues
        return fallback, trace
    return revised, trace
