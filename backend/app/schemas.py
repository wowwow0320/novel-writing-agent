import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.models import BibleCategory, BodySegmentLink, EpisodeStatus


class StoryCreate(BaseModel):
    title: str
    genre: str = ""
    synopsis: str | None = None
    world_setting: str | None = None
    global_rules: dict[str, Any] | None = None
    style_guide: str | None = None
    language: str = "KO"


class StoryUpdate(BaseModel):
    title: str | None = None
    genre: str | None = None
    synopsis: str | None = None
    world_setting: str | None = None
    global_rules: dict[str, Any] | None = None
    style_guide: str | None = None
    language: str | None = None
    work_summary: str | None = None


class StoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    genre: str
    synopsis: str | None
    world_setting: str | None = None
    global_rules: dict[str, Any] | None = None
    style_guide: str | None = None
    language: str
    work_summary: str | None = None
    created_at: datetime


class EpisodeCreate(BaseModel):
    chapter_num: int
    raw_memory: str | None = None
    ai_content: str | None = None
    summary: str | None = None
    status: EpisodeStatus = EpisodeStatus.draft


class EpisodeUpdate(BaseModel):
    chapter_num: int | None = None
    raw_memory: str | None = None
    summary: str | None = None
    chapter_events: list[dict[str, Any]] | None = None
    status: EpisodeStatus | None = None
    meta_tags: dict[str, Any] | None = None


class EpisodeBodyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    segment_index: int
    title: str | None
    content: str
    body_summary: str | None = None
    link_to_previous: BodySegmentLink | None
    parent_id: uuid.UUID | None = None
    meta_tags: dict[str, Any] | None = None


class EpisodeBodyItemIn(BaseModel):
    """본문 블록 한 덩어리. 배열 순서가 챕터 안 순서. 첫 항목의 link_to_previous는 저장 시 무시됨."""

    title: str | None = None
    content: str = ""
    body_summary: str | None = None
    link_to_previous: BodySegmentLink | None = None
    meta_tags: dict[str, Any] | None = None


class ReplaceEpisodeBodiesRequest(BaseModel):
    bodies: list[EpisodeBodyItemIn]


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    story_id: uuid.UUID
    chapter_num: int
    raw_memory: str | None
    ai_content: str | None
    summary: str | None
    chapter_events: list[dict[str, Any]] | None = None
    status: EpisodeStatus
    meta_tags: dict[str, Any] | None = None
    bodies: list[EpisodeBodyOut] = []


class BibleCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: BibleCategory
    name: str
    description: str | None = None
    metadata: dict[str, Any] | None = None


class BibleUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: BibleCategory | None = None
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class BibleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    story_id: uuid.UUID
    category: BibleCategory
    name: str
    description: str | None
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("extra", "metadata"),
        serialization_alias="metadata",
    )


ScenePlanBeat = Literal["기", "승", "전", "결", "보조", "회상", "에필로그"]
ScenePlanPOV = Literal["1st", "3rd_limited", "3rd_omniscient", "2nd", "mixed"]
ScenePlanTension = Literal["low", "mid", "high", "climax"]


class ScenePlanItem(BaseModel):
    id: str
    beat: ScenePlanBeat = "기"
    pov: ScenePlanPOV = "3rd_limited"
    goal: str = ""
    tension: ScenePlanTension = "mid"
    hint: str = ""
    approx_chars: int = 600


class ScenePlanRequest(BaseModel):
    episode_id: uuid.UUID
    raw_memory: str | None = None
    max_scenes: int = 6
    style_axes: dict[str, str] | None = Field(
        default=None,
        description="{length:'short|mid|long', register:'colloquial|literary', rhythm:'staccato|flowing'}",
    )


class ScenePlanResponse(BaseModel):
    scenes: list[ScenePlanItem]
    decision: dict[str, Any]


class ExpandedScene(BaseModel):
    scene_id: str
    content: str
    approx_chars: int
    label: str | None = None
    order: int | None = None


class MemoSegmentItem(BaseModel):
    """클라이언트가 /memo-qa-survey 응답 또는 expand에 되돌려 보내는 세그먼트."""

    id: str
    order: int
    label: str
    writer_memo: str


class MemoQaQuestionItem(BaseModel):
    id: str
    segment_id: str | None = None
    question: str
    options: list[str] = Field(..., min_length=2, max_length=5)
    freeform_hint: str | None = None


class MemoQaAnswerItem(BaseModel):
    """질문별 선택(보기 인덱스) + 직접 입력(자유)."""

    selected_index: int = 0
    freeform: str = ""


class MemoSurveySnapshot(BaseModel):
    segments: list[MemoSegmentItem] = Field(min_length=1)
    questions: list[MemoQaQuestionItem]


class MemoQaSurveyRequest(BaseModel):
    episode_id: uuid.UUID
    raw_memory: str | None = None
    style_axes: dict[str, str] | None = None


class MemoReadiness(BaseModel):
    score: float
    needs_questions: bool
    reasons: list[str]


class MemoEstimatedWork(BaseModel):
    segments: int
    draft_calls: int
    memory_searches: int
    stitch_calls: int


class MemoQaSurveyResponse(BaseModel):
    decision: dict[str, Any]
    segments: list[MemoSegmentItem]
    questions: list[MemoQaQuestionItem]
    readiness: MemoReadiness
    estimated_work: MemoEstimatedWork


class ExpandDraftRequest(BaseModel):
    episode_id: uuid.UUID
    raw_memory: str | None = None
    genre_override: str | None = None
    multi_step: bool | None = Field(
        default=None,
        description="None이면 길이·복잡도로 자동(single_pass/multi_step), True/False로 강제",
    )
    use_scene_plan: bool = False
    scene_plan: list[ScenePlanItem] | None = Field(
        default=None,
        description="주어지면 그대로 사용, 없고 use_scene_plan=true이면 서버가 즉석 생성",
    )
    regenerate_scene_ids: list[str] | None = Field(
        default=None,
        description="부분 재생성 시 재생성 대상 scene id 목록. context_used.regenerated 에 기록",
    )
    style_axes: dict[str, str] | None = None
    memory_mode: Literal["auto", "off"] = Field(
        default="auto",
        description="auto이면 세그먼트마다 장기 기억(RAG/관계/사건)을 자동 검색해 프롬프트에 주입",
    )
    memo_survey: MemoSurveySnapshot | None = Field(
        default=None,
        description="/memo-qa-survey 1단계 응답을 그대로. 있으면 오케스트 LLM 생략",
    )
    memo_qa_answers: dict[str, MemoQaAnswerItem] | None = Field(
        default=None,
        description="질문 id -> 답(선택지 인덱스+직접 입력). memo_survey 있을 때 사용(없으면 빈 답으로 처리)",
    )


class ExpandDraftResponse(BaseModel):
    ai_content: str
    context_used: dict[str, Any]
    scenes: list[ExpandedScene] | None = None
    scene_plan: list[ScenePlanItem] | None = None


class MemoryPreviewRequest(BaseModel):
    episode_id: uuid.UUID
    segment_memo: str
    previous_text: str = ""
    scene_hint: str = ""
    chapter_state: dict[str, Any] | None = None
    limit: int = 6


class MemoryPreviewResponse(BaseModel):
    bundle: dict[str, Any]
    prompt_block: str


class BibleExtractRequest(BaseModel):
    episode_id: uuid.UUID
    ai_content: str


class BibleExtractResponse(BaseModel):
    entries: list[dict[str, Any]]


class BibleCommitRequest(BaseModel):
    """미리보기(extract)로 받은 항목을 DB에 저장할 때 사용. LLM 재호출 없음."""

    entries: list[dict[str, Any]]


class BridgeRequest(BaseModel):
    summary_a: str
    raw_memory_b: str
    story_id: uuid.UUID | None = None
    anchor_excerpt: str | None = Field(default=None, description="직전 본문 끝·직전 블록 등 A 맥락 보강")


class BridgeResponse(BaseModel):
    suggestions: str


class RAGSearchRequest(BaseModel):
    story_id: uuid.UUID
    query: str
    limit: int = 5


class RAGSearchResult(BaseModel):
    source_type: Literal["episode", "bible", "summary"] = "episode"
    chunk_id: uuid.UUID | None = None
    bible_entry_id: uuid.UUID | None = None
    summary_node_id: uuid.UUID | None = None
    summary_node_key: str | None = None
    summary_level: str | None = None
    episode_id: uuid.UUID | None = None
    chapter_num: int = 0
    snippet: str
    score: float | None = None
    category: str | None = None
    color_tag: str | None = None
    segment_index: int | None = None
    paragraph_index: int | None = None
    heatmap_bucket: int = Field(default=1, description="1(약)~5(강) — UI 히트맵 진하기")
    parent_event_id: str | None = None
    parent_event_title: str | None = None


class EventMapChunkRef(BaseModel):
    chunk_id: uuid.UUID
    segment_index: int | None = None
    paragraph_index: int | None = None
    snippet: str
    category: str | None = None
    color_tag: str | None = None


class EventMapEntry(BaseModel):
    event_id: str
    title: str
    cause: str = ""
    outcome: str = ""
    turning_point: str = ""
    stakes: str = ""
    ref_count: int = 0
    refs: list[EventMapChunkRef] = Field(default_factory=list)


class EventMapResponse(BaseModel):
    episode_id: uuid.UUID
    chapter_num: int = 0
    events: list[EventMapEntry] = Field(default_factory=list)
    orphan_chunks: list[EventMapChunkRef] = Field(
        default_factory=list,
        description="어떤 이벤트에도 매칭되지 않은 paragraph chunk",
    )


class ConsistencyRequest(BaseModel):
    story_id: uuid.UUID
    focus_episode_id: uuid.UUID | None = Field(
        default=None,
        description="해당 챕터 본문만 깊게 검토(다른 화 발췌 제외)",
    )


class ConsistencyResponse(BaseModel):
    report: str


class StyleTransferRequest(BaseModel):
    text: str
    target_style: str


class StyleTransferResponse(BaseModel):
    text: str


class ExportRequest(BaseModel):
    story_id: uuid.UUID
    format: str = "txt"  # txt | pdf | epub


class FoundationAnalyzeRequest(BaseModel):
    story_input: str


class FoundationAnalyzeResponse(BaseModel):
    schema: dict[str, Any]
    extracted: dict[str, Any]
    question_check: dict[str, Any]


class IntakeAnswerEntry(BaseModel):
    q: str
    a: str
    ts: str = ""


class IntakeState(BaseModel):
    """클라이언트가 매 요청에 그대로 되돌려 보내는 세션 스냅샷.

    서버는 상태를 저장하지 않는다(Stateless). 프런트가 이 state 를 보유하고,
    answer/finalize 호출 시 통째로 재전송한다.
    """

    story_input: str
    extracted: dict[str, Any] = Field(default_factory=dict)
    question_check: dict[str, Any] = Field(default_factory=dict)
    answers: list[IntakeAnswerEntry] = Field(default_factory=list)
    iteration: int = 0


class IntakeStartRequest(BaseModel):
    story_input: str
    genre: str = ""
    language: str = "KO"


class IntakeAnswerRequest(BaseModel):
    state: IntakeState
    q: str
    a: str


class IntakeFinalizeRequest(BaseModel):
    state: IntakeState
    story_id: uuid.UUID
    merge_global_rules: bool = True


class IntakeResponse(BaseModel):
    state: IntakeState
    missing: list[str]
    suggested_questions: list[str]


class IntakeFinalizeResponse(BaseModel):
    applied_bible: int
    story: StoryOut
    world_setting_chars: int
    foundation_sync: dict[str, Any] | None = None


class DecisionRequest(BaseModel):
    draft: str
    sentence_count: int | None = None
    complexity_hint: float | None = None


class DecisionResponse(BaseModel):
    mode: Literal["single_pass", "multi_step"]
    metrics: dict[str, Any]
    thresholds: dict[str, Any]
    reason: str


class HierarchicalSummaryRequest(BaseModel):
    text: str
    paragraph_max_chars: int = 220
    chapter_max_chars: int = 420


class HierarchicalSummaryResponse(BaseModel):
    paragraph_summaries: list[str]
    events: list[dict[str, Any]]
    chapter_summary: str


class LogicConsistencyHarnessRequest(BaseModel):
    previous_text: str
    current_text: str
    allow_discontinuity: bool = False


class LogicConsistencyHarnessResponse(BaseModel):
    cosine_similarity: float
    transition_score: float = 0.0
    issues: list[str]
    needs_user_decision: bool


class BridgeVerifyRequest(BaseModel):
    story_id: uuid.UUID
    previous_text: str
    current_text: str
    episode_id: uuid.UUID | None = None
    chapter_summary: str | None = None
    chapter_events_json: str | None = Field(
        default=None,
        description="챕터 사건 궤적과의 정합성 판정에 넣을 JSON 문자열(선택)",
    )
    allow_discontinuity: bool = False
    top_k: int = 5


class BridgeVerifyResponse(BaseModel):
    logic: dict[str, Any]
    top_k_hits: list[dict[str, Any]]
    chapter_flow_note: str | None = None


# ==========================
# Module 03 — Critic / Review
# ==========================

ReviewSeverity = Literal["info", "warn", "error"]
ReviewCategory = Literal["continuity", "pov", "logic", "bible", "chapter_flow", "style"]
POVKind = Literal["1st", "3rd_limited", "3rd_omniscient", "2nd", "mixed", "unknown"]
TenseKind = Literal["past", "present", "mixed", "unknown"]


class ReviewIssue(BaseModel):
    id: str
    severity: ReviewSeverity = "warn"
    category: ReviewCategory = "continuity"
    message: str
    suggestion: str | None = None
    evidence: str | None = None
    block_id: uuid.UUID | None = None
    bypassed: bool = False
    bypass_reason: str | None = None


class POVDetection(BaseModel):
    pov: POVKind = "unknown"
    tense: TenseKind = "unknown"
    confidence: float = 0.0
    rationale: str = ""


class EpisodeReviewRequest(BaseModel):
    episode_id: uuid.UUID
    top_k: int = 6
    allow_discontinuity: bool | None = Field(
        default=None,
        description="명시 시 해당 에피소드의 meta_tags 기본값을 덮어쓴다",
    )
    include_pov: bool = True
    include_critic: bool = True


class EpisodeReviewResponse(BaseModel):
    episode_id: uuid.UUID
    issues: list[ReviewIssue]
    pov: POVDetection | None = None
    logic: dict[str, Any]
    top_k_hits: list[dict[str, Any]]
    chapter_flow_note: str | None = None
    allowed_bypasses: list[str] = Field(
        default_factory=list,
        description="meta_tags 기반으로 자동 우회된 카테고리 목록",
    )
    meta_tags: dict[str, Any] = Field(
        default_factory=dict,
        description="episode 레벨 meta_tags 스냅샷 (pov/tense/omnibus/time_jump/allow_discontinuity)",
    )


class EpisodeMetaTagsUpdate(BaseModel):
    """챕터(에피소드) 단위 meta_tags 갱신 — pov/tense/omnibus/time_jump/allow_discontinuity."""

    pov: POVKind | None = None
    tense: TenseKind | None = None
    omnibus: bool | None = None
    time_jump: bool | None = None
    allow_discontinuity: bool | None = None


class SemanticRouteRequest(BaseModel):
    message: str


class SemanticRouteResponse(BaseModel):
    intent: Literal["question", "create", "revise", "other"]
    confidence: float
    rationale: str


class GraphSubgraphResponse(BaseModel):
    nodes: list[dict[str, Any]]
    links: list[dict[str, Any]]
    depth: int
    ontology: dict[str, Any] | None = None
    # GRAPH_ENABLED=false 이면 Neo4j를 부르지 않고 nodes/links 는 빈 배열
    graph_source: Literal["disabled", "neo4j"] = "neo4j"


class GraphSyncResponse(BaseModel):
    enabled: bool
    entities: int
    relations: int = 0
    summaries: int = 0


class ConflictResolutionRequest(BaseModel):
    postgres_status: str | None = None
    graph_status: str | None = None
    policy: Literal["postgres", "graph", "manual"] | None = None


class ConflictResolutionResponse(BaseModel):
    resolved: str
    conflict: bool
    policy: str
    detail: str | None = None
