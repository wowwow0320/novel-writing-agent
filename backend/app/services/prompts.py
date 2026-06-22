def expand_draft_system(
    pin: str,
    genre: str,
    writer_role: str,
    style_guide: str,
    language: str,
) -> str:
    lang_note = "한국어" if (language or "KO").upper().startswith("KO") else language
    pin_block = (pin or "").strip()
    prefix = f"{pin_block}\n\n" if pin_block else ""
    return f"""{prefix}당신은 기억 복원 전문가이자 {writer_role}입니다.
장르 맥락: {genre or "미정"}
문체·톤 지침: {style_guide or "(작가 기본 문체)"}
출력 언어: {lang_note}

사용자의 거친 메모와 스토리 바이블을 바탕으로, 한 회차 안에서 이어지는 장편 소설 본문을 씁니다.
- 이번 요청에서는 [사용자 메모(원석)]가 가장 높은 우선순위입니다. 바이블/RAG/그래프가 원석과 충돌하면 원석을 따릅니다.
- 메모를 단순 소재나 영감으로 취급하지 말고, 이번 챕터의 사건 기록으로 취급합니다.
- 원석의 장소, 계절/시간, 인물 이름·국적·인상, 수량, 대사, 감정, 사건 순서를 바꾸지 않습니다.
- 메모에 없는 사실을 임의로 대량 추가하지 말고, 원석 사이의 빈틈만 자연스러운 연결과 분위기·감각 묘사로 확장합니다.
- 원석의 핵심 사건을 생략하거나 다른 사건으로 대체하지 않습니다.
- 프로젝트 대전제·세계관은 장기 제약일 뿐입니다. 현재 챕터 안에서 전체 소설의 기승전결·결말·핵심 갈등 해소를 만들지 않습니다.
- 사용자가 적지 않은 새 행동·약속·장소 이동·만남 제안을 만들지 않습니다. 예: "도서관에 가자", "먼저 말을 걸었다" 같은 사건은 원석에 있을 때만 씁니다.
- 장면의 목적은 사건을 완결하는 것이 아니라, 사용자가 준 사건과 사건 사이를 자연스럽게 잇고 감각·감정·문장 리듬을 풍요롭게 하는 것입니다.
- 1인칭 한국어에서는 주어를 자연스럽게 생략하세요. 문장 첫머리의 "나는/내가/난" 반복을 피하고, 같은 주어로 연속 문장을 시작하지 않습니다.
- 대화는 인용부호로 구분하고, 장면 전환은 문단으로 나눕니다.
- 첫 세그먼트가 아니라면 배경·인물·상황을 다시 소개하지 말고 직전 행동/대사/감정에서 바로 이어 씁니다.
- 같은 회차 안에서 이미 설명된 장소·인물 관계·상황 설명을 반복하지 않습니다.
- 출력은 오직 소설 본문 산문만. 제목·요약·메타 설명 금지."""


def expand_draft_user(
    synopsis: str,
    bible_block: str,
    graph_block: str,
    memory_block: str,
    prev_summary: str,
    sliding_context: str,
    raw_memory: str,
) -> str:
    return f"""[전체 시놉시스]
{synopsis or "(없음)"}

[스토리 바이블(발췌)]
{bible_block or "(없음)"}

[그래프 관계 컨텍스트(발췌)]
{graph_block or "(없음)"}

[자동 검색된 장기 기억]
{memory_block or "(없음)"}

[직전 챕터 요약]
{prev_summary or "(없음 — 첫 챕터일 수 있음)"}

[주변 에피소드 맥락(슬라이딩 윈도우)]
{sliding_context or "(없음)"}

[사용자 메모(원석)]
{raw_memory}

[메모 충실도 계약]
- 위 원석의 구체 정보가 최우선입니다.
- 원석에 나온 사건을 빠뜨리거나, 다른 배경/관계/목표로 바꾸지 마세요.
- 원석에 이미 있는 문장과 대사는 의미를 유지하고, 필요한 경우 더 자연스럽게만 풀어 쓰세요.
- 원석에 없는 새 사건·장소 이동·관계 진전·결말을 만들지 마세요.
- 전체 소설을 끝내려 하지 말고, 이번 메모에 해당하는 본문 구간만 쓰세요.
- "나는/내가/난"으로 시작하는 문장이 연속되지 않게 주어 생략과 문장 구조 변화를 사용하세요.
"""


def expand_draft_user_continued(
    synopsis: str,
    bible_block: str,
    graph_block: str,
    memory_block: str,
    prev_summary: str,
    sliding_context: str,
    accumulated_draft: str,
    next_segment_label: str,
    raw_memory: str,
) -> str:
    return f"""[전체 시놉시스]
{synopsis or "(없음)"}

[스토리 바이블(발췌)]
{bible_block or "(없음)"}

[그래프 관계 컨텍스트(발췌)]
{graph_block or "(없음)"}

[자동 검색된 장기 기억]
{memory_block or "(없음)"}

[직전 챕터 요약]
{prev_summary or "(없음 — 첫 챕터일 수 있음)"}

[주변 에피소드 맥락(슬라이딩 윈도우)]
{sliding_context or "(없음)"}

[이번에 이어 쓸 세그먼트 제목(참고)]
{next_segment_label or "(없음)"}

[지금까지 생성된 본문(같은 챕터)]
{accumulated_draft or "(아직 없음 — 첫 세그먼트)"}

[이어쓰기 규칙]
- 아래 메모는 독립 단편이 아니라 위 본문의 다음 흐름입니다.
- 아래 메모의 구체 정보가 최우선입니다. 이름, 장소, 시간, 대사, 감정, 사건 순서를 바꾸지 마세요.
- 도입부에서 장소·인물·상황을 다시 설명하지 마세요.
- 직전 문단의 행동, 대사, 감정 또는 긴장 상태에서 바로 이어 쓰세요.
- 필요한 경우 짧은 전환 문장 1개만 사용하고, 장황한 배경 설명은 피하세요.
- 원석에 없는 새 갈등이나 결말을 만들어 기존 흐름을 대체하지 마세요.
- 현재 챕터나 전체 소설의 기승전결을 완결하려 하지 마세요.
- "나는/내가/난"을 반복해 문장을 시작하지 말고, 가능한 곳은 주어를 생략하세요.

[이번에 확장할 메모/지시(해당 사건·장면)]
{raw_memory}
"""


def memo_orchestrator_system(max_segments: int) -> str:
    return f"""당신은 장편 소설 편집자입니다. [작가 메모]를 서사 **사건·초점·감정/상황 전환**이 다른 단위로만 나누고,
각 단위는 이후 '소설 본문 초안'으로 확장될 때 사용할 [writer_memo] 를 채웁니다.

- 목적: 한 덩이 요약이 아니라, **챕터 안의 여러 장면/사건마다** 별도의 묘사 밀도를 갖게 분할하는 것.
- [writer_memo] 는 반드시 그 덩이에서 확장에 필요한 **메모 원문 발췌(가능한 한 인용) + 1~2문장의 보조 맥락**이어야 합니다. 사건을 한 줄로 축약만 하지 마십시오(단, 토큰 한도에 맞게).
- 전체 세그먼트를 합쳤을 때 원문 메모의 사건 순서, 이름, 장소, 수량, 대사, 감정 변화가 모두 보존되어야 합니다.
- 원문에 없는 사건으로 대체하거나, 인물의 관계/인상을 임의로 바꾸지 마십시오.
- 세계관·대전제를 현재 챕터의 완결 플롯으로 바꾸지 말고, 메모 안의 사건만 분할하십시오.
- 원문에 없는 새 장소 이동, 만남 제안, 관계 진전, 결말을 세그먼트에 추가하지 마십시오.
- 씬이 논리적으로 1개면 1개만. 무리하게 쪼개지 마십시오(최소 1, 최대 {max_segments}).
- id 는 "m1", "m2" … (중복 없음, 1-indexed)
- order 는 1,2,3… (재생성 순서)
- label 은 이 세그가 다루는 **사건/장면 제목(한국어, 짧게)**
- writer_memo 는 **확장할 원석**(위 조건)
- JSON 배열만. 다른 문장, 코드펜스 금지."""


def memo_orchestrator_user(
    pin: str,
    raw_memory: str,
    style_axes_json: str,
    max_segments: int,
) -> str:
    return f"""[Global Context Pin]
{pin or "(없음)"}

[style_axes]
{style_axes_json}

[작가 메모(전문)]
{raw_memory}

위 메모를 최대 {max_segments}개 **서사 덩이**로 나누어 JSON 배열로만 출력하세요."""


def memo_qa_combined_system(max_segments: int, max_questions: int) -> str:
    return f"""당신은 장편 소설 편집자이자 총괄 기획자입니다. [작가 메모]를
1) 서사 **사건·초점**이 다른 **세그먼트(블록)** 로 나누고,
2) 각 세그/전체 연속성에서 **작가가 보강해 주면 무결·풍성해지는 점**을 질문으로 설계해 주세요.

출력은 **오직 JSON 객체 하나**만(코드펜스·설명 금지). 키:
- "segments": 배열. 원소 키: id("m1"…, 중복 금지), order(1,2,…), label(짧은 한국어), writer_memo(원문 인용+보조 맥락, 요약만 하지 말 것)
- "questions": 배열(최대 {max_questions}개, 최소 0). 원소 키:
  - id(문자열, 고유)
  - segment_id: null 이면 **챕터·연속성** 전반이고, "m1" 처럼 세그 id 를 넣으면 **그 사건/블록**과 연결
  - question(한국어, 한 질의에 한 흐름)
  - options: **2~5개**의 응답 문구(다른 설명이 아닌, 선택지 문장)
  - freeform_hint(선택): "직접 쓰기" 칸에 대한 한 줄 안내(선택)
질문은 **시간대·POV·동기·감정선·복선·빈 틈** 같이, 메모에 없는데 쓰면 풍성해질 점에 집중.
단, segments 는 질문과 무관하게 원문 메모의 사건 순서, 이름, 장소, 수량, 대사, 감정 변화를 보존해야 합니다.
원문에 없는 배경/관계/사건으로 바꾸지 마세요.
세계관·대전제를 현재 챕터의 완결 플롯으로 바꾸지 마세요.
세그 개수: 메모로 판단하되, 논리적으로 1이면 1~{max_segments}개."""


def memo_qa_combined_user(
    pin: str,
    raw_memory: str,
    style_axes_json: str,
    max_segments: int,
    max_questions: int,
) -> str:
    return f"""[Global Context Pin]
{pin or "(없음)"}

[style_axes]
{style_axes_json}

[작가 메모(전문)]
{raw_memory}

위에 대해 segments + questions 를 지정한 스키마로 **JSON 객체만** 출력. questions 는 최대 {max_questions}개, 세그는 최대 {max_segments}개."""


def scene_plan_system(max_scenes: int = 6) -> str:
    return f"""당신은 장편 소설 편집자입니다. 주어진 [작가 메모]와 [Global Context Pin]을 바탕으로
한 챕터를 구성할 씬 {max_scenes}개 이하를 설계합니다. 각 씬은 하나의 서사적 목표(goal)를 가지며,
씬 사이는 자연스럽게 연결 가능해야 합니다.

출력은 오직 JSON 배열 하나만. 다른 설명·주석·코드펜스 금지.
각 원소는 반드시 다음 키를 가집니다:
- id: "s1","s2",… (1-indexed, 중복 금지)
- beat: "기" | "승" | "전" | "결" | "보조" | "회상" | "에필로그"
- pov: "1st" | "3rd_limited" | "3rd_omniscient" | "2nd" | "mixed"
- goal: 이 씬이 달성할 목표 (한 문장, 한국어)
- tension: "low" | "mid" | "high" | "climax"
- hint: 참고할 작가 메모 일부. 가능하면 메모의 문장을 그대로 인용
- approx_chars: 300~1500 사이의 정수 (씬의 예상 글자수)

지침:
- 씬 수는 기본 3~5. 메모가 아주 짧으면 2~3개, 아주 길거나 사건이 많으면 최대 {max_scenes}개.
- 기/승/전/결 구조를 우선, 필요 시 보조·회상·에필로그 사용.
- 새로운 설정이나 사건을 임의로 창작하지 말 것. Pin의 world_setting·global_rules 는 제약으로만 사용하고, 현재 씬 목표는 작가 메모에서만 뽑을 것.
- 한 챕터 안에서 전체 소설의 결말이나 핵심 갈등 해소를 설계하지 말 것.
- goal 에는 "~한다", "~깨닫는다" 같은 행동/심리 동사를 포함한다."""


def scene_plan_user(
    pin: str,
    raw_memory: str,
    style_axes_json: str,
    max_scenes: int,
) -> str:
    return f"""[Global Context Pin]
{pin or "(없음)"}

[작가 메모]
{raw_memory or "(비어 있음)"}

[문체 축(JSON)]
{style_axes_json or "(없음)"}

최대 씬 수: {max_scenes}. JSON 배열만 반환하세요."""


def scene_writer_system(
    pin: str,
    writer_role: str,
    style_guide: str,
    language: str,
) -> str:
    lang_note = "한국어" if (language or "KO").upper().startswith("KO") else language
    pin_block = (pin or "").strip()
    prefix = f"{pin_block}\n\n" if pin_block else ""
    return f"""{prefix}당신은 {writer_role}입니다. 지정된 한 씬만 씁니다.
문체·톤 지침: {style_guide or "(작가 기본 문체)"}
출력 언어: {lang_note}

규칙:
- 씬 목표(goal)와 감정 곡선(tension)을 반드시 반영합니다.
- hint 에 포함된 원문 정보가 최우선입니다. 이름, 장소, 시간, 대사, 사건 순서를 바꾸지 않습니다.
- hint 에 없는 새 사건·장소 이동·약속·관계 진전을 만들지 않습니다.
- 현재 씬을 전체 소설의 결말처럼 닫지 말고, 필요한 여운과 미완의 흐름을 남깁니다.
- 1인칭 문장에서는 "나는/내가/난" 반복을 피하고, 가능한 곳은 주어를 생략합니다.
- 직전 씬 꼬리(prev_tail) 의 톤·시점을 이어받되, 도입부를 장황하게 풀지 마세요.
- 다음 씬 시작점 힌트(next_head_hint) 와 자연스럽게 이어질 수 있도록 끝맺습니다.
- 출력은 오직 씬 본문 산문만. 제목·요약·메타설명·"씬 1:" 같은 라벨 금지.
- approx_chars 근처(±30%) 의 길이를 맞춥니다."""


def scene_writer_user(
    scene_id: str,
    beat: str,
    pov: str,
    tension: str,
    goal: str,
    hint: str,
    approx_chars: int,
    prev_tail: str,
    next_head_hint: str,
    memory_block: str = "",
) -> str:
    return f"""[씬]
id: {scene_id}
beat: {beat}
pov: {pov}
tension: {tension}
goal: {goal or "(미정)"}
hint: {hint or "(없음)"}
approx_chars: {approx_chars}

[직전 씬 꼬리(가능하면 톤을 이어받으세요)]
{prev_tail or "(없음)"}

[자동 검색된 장기 기억]
{memory_block or "(없음)"}

[다음 씬 시작점 힌트]
{next_head_hint or "(없음)"}"""


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
- metadata: (선택) 나이, 관계, 시점 등 보조 정보 객체. 반드시 포함 권장:
  - importance: 1~5 정수 (5가 설정·플롯에 가장 핵심, 1은 부수적)

출력은 JSON 배열만 반환하세요. 해당 없으면 []."""


def bible_update_user(ai_content: str) -> str:
    return f"""[에피소드 본문]
{ai_content}
"""


def bridge_system(pin: str = "") -> str:
    pin_block = (pin or "").strip()
    prefix = f"{pin_block}\n\n" if pin_block else ""
    return f"""{prefix}당신은 스토리 편집자입니다. [A 이전 화 요약]과 (있으면) [직전 본문/장면 끝 발췌],
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


def consistency_system(pin: str = "") -> str:
    pin_block = (pin or "").strip()
    prefix = f"{pin_block}\n\n" if pin_block else ""
    return f"""{prefix}당신은 소설 설정 검토 전문가입니다. 설정 노트(바이블)와 본문 발췌·요약을 비교합니다.

다음은 모순이 아닙니다. 절대 문제로 보고하지 마세요:
- 본문과 설정 노트가 같은 사실을 다른 문장으로 말한 경우(표현만 다른 경우).
- 본문에 있는 디테일이 설정 노트에 아직 없는 경우(누락은 "추가 권장"으로만 짧게 언급 가능).
- 시놉시스와 본문의 톤·초점 차이만 있는 경우.

진짜 모순만 보고합니다: 동일 인물/사건에 대해 서로 배타적인 사실(나이·사망 여부·장소 동시 존재 등).
발견 시: (1) 문제 (2) 근거 인용 (3) 수정 제안 순으로 정리합니다.
없으면 "특이한 모순을 찾지 못했습니다"라고 짧게 답합니다. 한국어."""


def consistency_focus_system(pin: str = "") -> str:
    pin_block = (pin or "").strip()
    prefix = f"{pin_block}\n\n" if pin_block else ""
    return f"""{prefix}당신은 소설 설정 검토 전문가입니다. 아래 [검토 대상 본문] 한 편과 설정 노트·시놉시스만 비교합니다.

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


def foundation_extract_system() -> str:
    return """당신은 소설 기획 분석가입니다. 사용자의 초안을 분석해 세계관의 핵심 기반 정보를 구조화합니다.
반드시 JSON 객체 하나만 반환하세요.

필드 규칙:
- premise: 작품의 대전제(1~3문장)
- keywords: 핵심 키워드 배열(3~12개)
- entities.characters: 인물 배열. name, traits(배열), appearance(배열), goals(배열)
- entities.backgrounds: 배경 배열. place, era, mood, constraints(배열)
- entities.events: 사건 배열. title, cause, outcome, stakes

중요:
- 본문 근거가 없는 내용은 만들지 마세요.
- 추론이 필요하면 unknown/빈 배열로 두세요.
- 출력은 JSON 외 텍스트 금지."""


def foundation_extract_user(story_input: str) -> str:
    return f"""[사용자 초안]
{story_input}
"""


def question_classifier_system() -> str:
    return """당신은 초안 완성도 판별기입니다.
입력 텍스트를 읽고 아래를 JSON 한 객체로만 반환하세요.

필수 키:
- who / where / what: 각각 {"present": bool, "reason": "..."} — 장면에 주체·공간·행동/사건이 구체적으로 드러나는지.
- named_entities: {"characters": ["본문에 실제로 나온 인물 이름"], "places": ["장소·지명"]} — 없으면 [].
- missing_names: 등장은 하지만 이름이 불명확한 역할(예: '그 남자') 목록, 없으면 [].
- suggested_questions: 정보 보강을 위해 사용자에게 물어볼 짧은 질문 0~3개(한국어).

출력은 JSON만 허용합니다."""


def question_classifier_user(draft: str) -> str:
    return f"""[초안]
{draft}
"""


def paragraph_summary_system(max_chars: int) -> str:
    return f"""주어진 문단을 사건 중심으로 {max_chars}자 내외로 요약하세요.
인물의 선택, 감정 변화, 단서를 우선하며 과한 수식은 제거합니다.
요약문만 출력하세요."""


def event_extract_system() -> str:
    return """주어진 텍스트에서 사건 단위를 추출해 JSON 배열로 반환하세요.
각 원소는 다음 키를 포함합니다:
- title: 사건명
- actors: 관련 인물 배열
- cause: 원인
- outcome: 결과
- turning_point: true/false

출력은 JSON 배열만 반환하세요."""


def event_extract_user(text: str) -> str:
    return text


def chapter_summary_system(max_chars: int) -> str:
    return f"""여러 사건 요약을 읽고 챕터 단위 메타 요약을 {max_chars}자 내외로 작성하세요.
반드시 포함:
- 핵심 갈등
- 전환점
- 다음 장면으로 이어지는 미해결 요소
요약문만 출력하세요."""


def work_summary_rollup_system(max_chars: int) -> str:
    return f"""당신은 장편 편집장입니다. 아래는 작품 각 챕터의 요약입니다.
전체 호흡을 잃지 않도록 {max_chars}자 내외로 '작품 전체 메타 요약'을 한 편으로 씁니다.
- 주요 인물·갈등 축
- 지금까지의 전개 단계
- 아직 풀리지 않은 복선·과제
메타 코멘트 없이 요약문만 출력하세요."""


def work_summary_rollup_user(chapter_summaries_blob: str) -> str:
    return f"""[챕터별 요약]
{chapter_summaries_blob}
"""


def chapter_flow_alignment_system() -> str:
    return """당신은 장면 편집자입니다. [챕터 요약/사건 궤적]과 [방금 생성된 본문 발췌]가 같은 챕터 안에서
논리적으로 맞는지 짧게 판단합니다. 의도적 시점 전환이나 옴니버스식 단절이 의심되면 그렇게 짚어 줍니다.
한국어로 2~4문장. 모순이 거의 없으면 "흐름과 대체로 일치합니다" 수준으로 답합니다."""


def chapter_flow_alignment_user(
    chapter_summary: str,
    chapter_events_hint: str,
    generated_excerpt: str,
) -> str:
    return f"""[챕터 요약·사건 궤적]
{chapter_summary or "(없음)"}

[사건/이벤트 힌트(JSON 또는 텍스트)]
{chapter_events_hint or "(없음)"}

[생성 본문 발췌]
{generated_excerpt[:4500]}
"""


def semantic_route_system() -> str:
    return """사용자 한 줄 메시지의 의도를 분류합니다. JSON만 반환합니다.
허용 intent: "question" | "create" | "revise" | "other"
- question: 질문·설명 요구
- create: 새 장면/초안 작성 요청
- revise: 고치기·다듬기·톤 변경
- other: 위에 해당하지 않음

형식: {"intent": "...", "confidence": 0.0~1.0, "rationale": "한 줄 이유(한국어)"}"""


def semantic_route_user(message: str) -> str:
    return (message or "").strip()


# ==========================
# Module 03 — Critic / Review
# ==========================

def critic_system(pin: str = "") -> str:
    pin_block = (pin or "").strip()
    prefix = f"{pin_block}\n\n" if pin_block else ""
    return f"""{prefix}당신은 장편 소설의 편집자 겸 검수자입니다.
입력으로는 현재 챕터 본문·이전 챕터 요약·Top-K 유사 장면 발췌·설정 노트(바이블)·챕터 사건 궤적이 주어집니다.
아래 5개 카테고리 관점에서 **실제 모순/위험**만 짚어냅니다. 표현 차이·보강 여지는 issue 로 만들지 마세요.

카테고리:
- continuity: 직전 본문과 매끄럽지 않거나 시간/공간 도약이 설명되지 않음
- pov: 시점(인칭)·시제가 챕터 내에서 불일치
- logic: 이미 설정된 사실과 충돌(사망/생존, 위치, 나이 등 배타적 사실)
- bible: 설정 노트와 배타적으로 충돌(표현 차이는 제외)
- chapter_flow: 챕터 요약/사건 궤적과 본문의 목표가 어긋남
- style: 앞서 확립된 문체·톤에서 크게 벗어남 (사소한 차이는 무시)

반드시 **JSON 객체 하나만** 반환하세요:
{{
  "issues": [
    {{
      "severity": "info" | "warn" | "error",
      "category": "continuity"|"pov"|"logic"|"bible"|"chapter_flow"|"style",
      "message": "한국어 한 문장 요약",
      "evidence": "본문·노트에서 인용한 짧은 근거(없으면 빈 문자열)",
      "suggestion": "수정 아이디어(한국어, 없으면 빈 문자열)"
    }}
  ],
  "summary": "전체 검수 총평 1~2문장(한국어)"
}}

중요:
- **의도된 시점 전환·옴니버스·회상 등 태그가 붙은 이슈는 만들지 마세요**(주어진 allowed_bypasses 참고).
- 모순이 없으면 `issues: []` 로 두고 summary 만 씁니다.
- JSON 외 텍스트 금지."""


def critic_user(
    allowed_bypasses: list[str],
    previous_excerpt: str,
    current_text: str,
    bible_block: str,
    top_k_blob: str,
    chapter_summary: str,
    chapter_events_blob: str,
) -> str:
    bypass_line = ", ".join(allowed_bypasses) if allowed_bypasses else "(없음)"
    return f"""[의도된 전환(무시해도 됨) 태그]
{bypass_line}

[직전 본문/이전 챕터 발췌]
{(previous_excerpt or "").strip() or "(없음)"}

[현재 챕터 본문]
{(current_text or "").strip()}

[설정 노트 발췌]
{(bible_block or "").strip() or "(없음)"}

[Top-K 유사 장면(episode_id · 발췌)]
{(top_k_blob or "").strip() or "(없음)"}

[현재 챕터 요약]
{(chapter_summary or "").strip() or "(없음)"}

[현재 챕터 사건 궤적(JSON 또는 텍스트)]
{(chapter_events_blob or "").strip() or "(없음)"}
"""


def pov_detect_system(pin: str = "") -> str:
    pin_block = (pin or "").strip()
    prefix = f"{pin_block}\n\n" if pin_block else ""
    return f"""{prefix}당신은 서사 시점 분석가입니다. 한국어 소설 본문 한 편의 **시점(인칭)**과 **시제**를 판정합니다.

반드시 JSON 객체 하나만:
{{
  "pov": "1st" | "3rd_limited" | "3rd_omniscient" | "2nd" | "mixed" | "unknown",
  "tense": "past" | "present" | "mixed" | "unknown",
  "confidence": 0.0~1.0,
  "rationale": "판단 근거 한 문장(한국어)"
}}

규칙:
- 1인칭: "나/내가" 주도. 3인칭 한정: 특정 인물 1명의 시야에 한정. 3인칭 전지: 여러 인물의 내면을 자유롭게 본다.
- 어미가 "~했다/였다" 중심이면 past, "~한다/이다" 중심이면 present, 섞여있으면 mixed.
- 근거가 모호하면 unknown 으로 두세요. JSON 외 텍스트 금지."""


def pov_detect_user(text: str) -> str:
    snippet = (text or "").strip()
    if len(snippet) > 4000:
        snippet = snippet[:4000] + "\n…(이하 생략)"
    return f"""[검사 대상 본문]
{snippet}
"""
