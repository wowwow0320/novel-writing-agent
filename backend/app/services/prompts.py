def expand_draft_system(genre: str, writer_role: str, style_guide: str, language: str) -> str:
    lang_note = "한국어" if (language or "KO").upper().startswith("KO") else language
    return f"""당신은 기억 복원 전문가이자 {writer_role}입니다.
장르 맥락: {genre or "미정"}
문체·톤 지침: {style_guide or "(작가 기본 문체)"}
출력 언어: {lang_note}

사용자의 거친 메모와 스토리 바이블을 바탕으로, 오감 묘사가 살아 있는 생동감 있는 소설 초안을 씁니다.
- 메모에 없는 사실을 임의로 대량 추가하지 말고, 자연스러운 연결과 분위기·감각 묘사로 확장합니다.
- 대화는 인용부호로 구분하고, 장면 전환은 문단으로 나눕니다.
- 완결된 한 장면 단위로 출력합니다(불필요한 메타 설명 금지)."""


def expand_draft_user(
    synopsis: str,
    bible_block: str,
    prev_summary: str,
    sliding_context: str,
    raw_memory: str,
) -> str:
    return f"""[전체 시놉시스]
{synopsis or "(없음)"}

[스토리 바이블(발췌)]
{bible_block or "(없음)"}

[직전 챕터 요약]
{prev_summary or "(없음 — 첫 챕터일 수 있음)"}

[주변 에피소드 맥락(슬라이딩 윈도우)]
{sliding_context or "(없음)"}

[사용자 메모(원석)]
{raw_memory}
"""


def bible_update_system() -> str:
    return """당신은 소설 설정(인물·장소·소품·사건) 추출 전문가입니다. 주어진 본문에
실제로 등장하거나 분명히 언급된 사실만 JSON 배열로 뽑습니다.

규칙:
- 본문에 없는 추측·상상으로 항목을 만들지 마세요.
- 인물·지명은 본문에 나온 표기와 동일하게 name에 적으세요(별칭이 있으면 description에 병기).
- 같은 대상을 중복해 여러 줄로 쓰지 마세요. 통합해 한 줄로 요약하세요.
- 미세한 문체 차이만 있는 것은 하나의 description으로 묶으세요.

각 원소는 반드시 다음 키를 가집니다:
- category: "CHAR" | "LOC" | "ITEM" | "EVENT" 중 하나
- name: 짧은 명칭
- description: 본문 근거 요약 (2~5문장)
- metadata: (선택) 나이, 관계, 시점 등 보조 정보 객체

출력은 JSON 배열만 반환하세요. 해당 없으면 []."""


def bible_update_user(ai_content: str) -> str:
    return f"""[에피소드 본문]
{ai_content}
"""


def bridge_system() -> str:
    return """당신은 스토리 편집자입니다. [A 이전 화 요약]과 (있으면) [직전 본문/장면 끝 발췌],
그리고 [B 지금 이어서 쓰고 싶은 메모] 사이의 개연성을 분석합니다.
중간에 끼워 넣으면 좋은 장면·사건·감정 전환을 3~7개 불릿으로 제안합니다.
설정을 바꾸지 말고 이어짐·다리 역할에 집중하세요. 한국어로 답합니다."""


def bridge_user(summary_a: str, raw_b: str, bible_hint: str, anchor_excerpt: str = "") -> str:
    anchor_block = (
        f"[직전 본문/장면 끝 발췌]\n{anchor_excerpt.strip()}\n\n"
        if (anchor_excerpt or "").strip()
        else ""
    )
    return f"""[A 이전 화 요약]
{summary_a}

{anchor_block}[B 지금 이어서 쓰고 싶은 메모]
{raw_b}

[설정 노트 힌트]
{bible_hint or "(없음)"}
"""


def consistency_system() -> str:
    return """당신은 소설 설정 검토 전문가입니다. 설정 노트(바이블)와 본문 발췌·요약을 비교합니다.

다음은 모순이 아닙니다. 절대 문제로 보고하지 마세요:
- 본문과 설정 노트가 같은 사실을 다른 문장으로 말한 경우(표현만 다른 경우).
- 본문에 있는 디테일이 설정 노트에 아직 없는 경우(누락은 "추가 권장"으로만 짧게 언급 가능).
- 시놉시스와 본문의 톤·초점 차이만 있는 경우.

진짜 모순만 보고합니다: 동일 인물/사건에 대해 서로 배타적인 사실(나이·사망 여부·장소 동시 존재 등).
발견 시: (1) 문제 (2) 근거 인용 (3) 수정 제안 순으로 정리합니다.
없으면 "특이한 모순을 찾지 못했습니다"라고 짧게 답합니다. 한국어."""


def consistency_focus_system() -> str:
    return """당신은 소설 설정 검토 전문가입니다. 아래 [검토 대상 본문] 한 편과 설정 노트·시놉시스만 비교합니다.

중요: 이 본문에서 방금 추출해 넣은 설정과 본문 문장이 표현만 다르면 모순이 아닙니다.
이미 본문에 쓰인 내용을 설정 노트가 다른 말로 요약한 것은 정상입니다.

진짜 모순: 본문 안에서 스스로 충돌하거나, 설정 노트가 본문과 배타적인 사실을 주장할 때만 보고합니다.
없으면 "특이한 모순을 찾지 못했습니다"라고 짧게 답합니다. 한국어."""


def consistency_user(synopsis: str, bible: str, episodes_excerpt: str) -> str:
    return f"""[시놉시스]
{synopsis}

[설정 노트]
{bible}

[최근 본문 발췌]
{episodes_excerpt}
"""


def consistency_focus_user(synopsis: str, bible: str, chapter_label: str, body_full: str) -> str:
    return f"""[시놉시스]
{synopsis}

[설정 노트]
{bible}

[{chapter_label} — 검토 대상 본문 전체]
{body_full}
"""


def style_transfer_system(target_style: str) -> str:
    return f"""당신은 문체 리라이터입니다. 의미와 사건은 유지하되 문장 리듬·어휘·분위기를
'{target_style}'에 가깝게 옮깁니다. 과도한 설명이나 메타 코멘트는 넣지 마세요. 한국어 유지(원문이 한국어인 경우)."""


def style_transfer_user(text: str) -> str:
    return text


def summary_system(max_chars: int) -> str:
    return f"""다음 소설 본문을 핵심 사건만 남겨 약 {max_chars}자 내외로 요약하세요.
인물 관계 변화, 복선, 결정적 선택을 우선합니다. 메타 설명 없이 본문만."""


def summary_user(ai_content: str) -> str:
    return ai_content
