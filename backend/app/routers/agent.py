import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.models import BibleCategory, Episode, EpisodeChunk, Story, StoryBibleEntry, StorySummaryNode
from app.schemas import (
    BibleCommitRequest,
    BibleExtractRequest,
    BibleExtractResponse,
    BridgeRequest,
    BridgeResponse,
    BridgeVerifyRequest,
    BridgeVerifyResponse,
    ConsistencyRequest,
    ConsistencyResponse,
    DecisionRequest,
    DecisionResponse,
    EpisodeReviewRequest,
    EpisodeReviewResponse,
    ExpandDraftRequest,
    ExpandDraftResponse,
    ExpandedScene,
    ExportRequest,
    FoundationAnalyzeRequest,
    FoundationAnalyzeResponse,
    GraphSubgraphResponse,
    GraphSyncResponse,
    HierarchicalSummaryRequest,
    HierarchicalSummaryResponse,
    ConflictResolutionRequest,
    ConflictResolutionResponse,
    IntakeAnswerRequest,
    IntakeFinalizeRequest,
    IntakeFinalizeResponse,
    IntakeResponse,
    IntakeStartRequest,
    IntakeState,
    LogicConsistencyHarnessRequest,
    LogicConsistencyHarnessResponse,
    MemoryPreviewRequest,
    MemoryPreviewResponse,
    MemoQaSurveyRequest,
    MemoQaSurveyResponse,
    MemoSegmentItem,
    ScenePlanItem,
    ScenePlanRequest,
    ScenePlanResponse,
    SemanticRouteRequest,
    SemanticRouteResponse,
    RAGSearchRequest,
    RAGSearchResult,
    EventMapChunkRef,
    EventMapEntry,
    EventMapResponse,
    StoryOut,
    StyleTransferRequest,
    StyleTransferResponse,
)
from app.services import llm, rag
from app.services.episode_text import full_episode_writing_text
from app.services.context_builder import (
    build_writer_context,
    fetch_bible,
    format_bible,
    format_global_context_pin,
    load_story_episodes,
)
from app.services.critic import run_episode_review
from app.services.draft_guard import revise_draft_if_needed
from app.services.event_map import build_event_map, heatmap_bucket_from_score
from app.services.intake import (
    append_answer,
    finalize_story_world,
    intake_run_once,
)
from app.services.memo_orchestrator import (
    MemoSegment,
    apply_memo_qa_answers,
    assess_memo_readiness,
    estimate_memo_work,
    orchestrate_memo_segments,
    run_memo_qa_survey,
    tail_for_prompt,
)
from app.services.scene_planner import (
    build_neighbors,
    plan_scenes,
    stitch_scenes,
    stitch_with_llm,
    write_scene,
)
from app.services.export import build_story_text, to_epub_bytes, to_pdf_bytes, to_txt_bytes
from app.services.json_extract import parse_llm_json_array
from app.services.graph_sync import (
    conflict_resolution_harness,
    extract_graph_facts,
    graph_counts,
    graph_ontology,
    graph_subgraph,
    project_episode_memory_to_graph,
)
from app.services.memory_retrieval import (
    build_memory_bundle,
    format_memory_bundle_for_prompt,
    memory_trace_from_bundle,
)
from app.services.memory_store import (
    record_generation_run,
    upsert_bible_entries_to_memory,
    upsert_chapter_events_to_memory,
    upsert_graph_facts_to_memory,
)
from app.services.summary_tree import (
    rebuild_episode_summary_tree,
    rebuild_story_summary_tree,
    search_summary_nodes,
)
from app.services.prompts import (
    bible_update_system,
    bible_update_user,
    bridge_system,
    bridge_user,
    consistency_focus_system,
    consistency_focus_user,
    consistency_system,
    consistency_user,
    expand_draft_system,
    expand_draft_user,
    expand_draft_user_continued,
    style_transfer_system,
    style_transfer_user,
)
from app.services.story_pipeline import (
    WORLD_SCHEMA,
    bridge_continuity_bundle,
    build_hierarchical_summary,
    classify_required_elements,
    decide_generation_mode,
    events_for_jsonb,
    extract_foundation,
    hierarchical_from_block_texts,
    logic_consistency_harness,
    rollup_story_work_summary,
    semantic_route_fallback,
    semantic_route_user_intent,
    split_draft_for_multi_step,
)

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


def _parse_bible_category(cat_s: str) -> BibleCategory:
    u = (cat_s or "CHAR").upper().strip()
    mapping = {
        "CHAR": BibleCategory.char,
        "LOC": BibleCategory.loc,
        "ITEM": BibleCategory.item,
        "EVENT": BibleCategory.event,
    }
    return mapping.get(u, BibleCategory.char)


def _persist_bible_entries(db: AsyncSession, story_id: uuid.UUID, items: list[dict[str, Any]]) -> list[StoryBibleEntry]:
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
        db.add(row)
        created.append(row)
    return created


@router.post("/foundation/analyze", response_model=FoundationAnalyzeResponse)
async def foundation_analyze(body: FoundationAnalyzeRequest) -> FoundationAnalyzeResponse:
    try:
        extracted = await extract_foundation(body.story_input)
        question = await classify_required_elements(body.story_input)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return FoundationAnalyzeResponse(
        schema=WORLD_SCHEMA,
        extracted=extracted,
        question_check=question,
    )


def _intake_response(state: IntakeState) -> IntakeResponse:
    qc = state.question_check if isinstance(state.question_check, dict) else {}
    missing = qc.get("missing")
    if not isinstance(missing, list):
        missing = [k for k in ("who", "where", "what") if not bool(qc.get(k, {}).get("present"))]
    raw_qs = qc.get("suggested_questions")
    suggested = (
        [str(q).strip() for q in raw_qs if str(q).strip()][:3]
        if isinstance(raw_qs, list)
        else []
    )
    return IntakeResponse(state=state, missing=[str(m) for m in missing], suggested_questions=suggested)


@router.post("/intake/start", response_model=IntakeResponse)
async def intake_start(body: IntakeStartRequest) -> IntakeResponse:
    state = IntakeState(story_input=body.story_input.strip())
    try:
        state = await intake_run_once(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return _intake_response(state)


@router.post("/intake/answer", response_model=IntakeResponse)
async def intake_answer(body: IntakeAnswerRequest) -> IntakeResponse:
    merged = append_answer(body.state, body.q, body.a)
    try:
        merged = await intake_run_once(merged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return _intake_response(merged)


@router.post("/intake/finalize", response_model=IntakeFinalizeResponse)
async def intake_finalize(
    body: IntakeFinalizeRequest,
    db: AsyncSession = Depends(get_db),
) -> IntakeFinalizeResponse:
    try:
        result = await finalize_story_world(
            db,
            body.story_id,
            body.state,
            merge_global_rules=body.merge_global_rules,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    await db.commit()
    story = await db.get(Story, body.story_id)
    if not story:
        raise HTTPException(404, "story not found")
    return IntakeFinalizeResponse(
        applied_bible=int(result.get("bible_seeded", 0)),
        story=StoryOut.model_validate(story),
        world_setting_chars=int(result.get("world_setting_chars", 0)),
        foundation_sync=result.get("foundation_sync") if isinstance(result.get("foundation_sync"), dict) else None,
    )


@router.post("/decision", response_model=DecisionResponse)
async def decision_route(body: DecisionRequest) -> DecisionResponse:
    payload = decide_generation_mode(
        body.draft,
        sentence_count=body.sentence_count,
        complexity_hint=body.complexity_hint,
    )
    return DecisionResponse(**payload)


@router.post("/hierarchical-summary", response_model=HierarchicalSummaryResponse)
async def hierarchical_summary(body: HierarchicalSummaryRequest) -> HierarchicalSummaryResponse:
    try:
        payload = await build_hierarchical_summary(
            body.text,
            paragraph_max_chars=body.paragraph_max_chars,
            chapter_max_chars=body.chapter_max_chars,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return HierarchicalSummaryResponse(**payload)


@router.post("/summary-tree/rebuild/{story_id}")
async def summary_tree_rebuild(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    story = await db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "story not found")
    try:
        result = await rebuild_story_summary_tree(db, story_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"요약 트리 재빌드 실패: {e}") from e
    graph_sync: dict[str, Any] = {"enabled": False}
    if get_settings().graph_enabled:
        try:
            graph_sync = await project_episode_memory_to_graph(db, story_id, None)
        except RuntimeError as e:
            graph_sync = {"enabled": True, "error": str(e)[:1200]}
    await db.commit()
    result["graph_sync"] = graph_sync
    return result


@router.get("/summary-tree/{story_id}")
async def summary_tree_get(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    story = await db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "story not found")
    rows = list(
        (
            await db.execute(
                select(StorySummaryNode)
                .where(StorySummaryNode.story_id == story_id)
                .order_by(
                    StorySummaryNode.depth.asc(),
                    StorySummaryNode.chapter_start.asc().nullsfirst(),
                    StorySummaryNode.ordinal.asc().nullsfirst(),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "story_id": str(story_id),
        "nodes": [
            {
                "id": str(row.id),
                "node_key": row.node_key,
                "level": row.level,
                "parent_id": str(row.parent_id) if row.parent_id else None,
                "root_id": str(row.root_id) if row.root_id else None,
                "depth": row.depth,
                "path": row.path or [],
                "chapter_start": row.chapter_start,
                "chapter_end": row.chapter_end,
                "summary": row.summary,
                "keywords": row.keywords or [],
                "source_body_ids": row.source_body_ids or [],
                "source_episode_ids": row.source_episode_ids or [],
                "entity_ids": row.entity_ids or [],
                "event_ids": row.event_ids or [],
                "relationship_ids": row.relationship_ids or [],
                "token_count": row.token_count,
                "coverage_score": row.coverage_score,
                "stale": row.stale,
            }
            for row in rows
        ],
    }


@router.post("/harness/logic-consistency", response_model=LogicConsistencyHarnessResponse)
async def harness_logic_consistency(
    body: LogicConsistencyHarnessRequest,
) -> LogicConsistencyHarnessResponse:
    payload = logic_consistency_harness(
        body.previous_text,
        body.current_text,
        allow_discontinuity=body.allow_discontinuity,
    )
    return LogicConsistencyHarnessResponse(**payload)


@router.post("/harness/bridge-verify", response_model=BridgeVerifyResponse)
async def harness_bridge_verify(
    body: BridgeVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> BridgeVerifyResponse:
    payload = await bridge_continuity_bundle(
        db,
        body.story_id,
        body.previous_text,
        body.current_text,
        chapter_summary=body.chapter_summary,
        chapter_events_blob=body.chapter_events_json,
        allow_discontinuity=body.allow_discontinuity,
        top_k=body.top_k,
    )
    return BridgeVerifyResponse(**payload)


@router.post("/review/episode/{episode_id}", response_model=EpisodeReviewResponse)
async def review_episode(
    episode_id: uuid.UUID,
    body: EpisodeReviewRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> EpisodeReviewResponse:
    """수동 트리거 검수(`03_REVIEW_COHERENCE.md`).

    - `bridge_continuity_bundle` + `detect_pov` + Critic LLM 을 합쳐 이슈 카드 + allowed_bypasses 반환.
    - 본문이 비어 있으면 400, 에피소드 없음은 404.
    """
    req = body or EpisodeReviewRequest(episode_id=episode_id)
    # body.episode_id 와 URL path 불일치 방지: URL 우선.
    try:
        payload = await run_episode_review(
            db,
            episode_id,
            top_k=max(1, min(12, int(req.top_k or 6))),
            include_pov=bool(req.include_pov),
            include_critic=bool(req.include_critic),
            allow_discontinuity_override=req.allow_discontinuity,
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg else 400
        raise HTTPException(status_code=status, detail=msg) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    payload.pop("summary_note", None)
    return EpisodeReviewResponse(**payload)


@router.post("/harness/semantic-route", response_model=SemanticRouteResponse)
async def harness_semantic_route(body: SemanticRouteRequest) -> SemanticRouteResponse:
    try:
        p = await semantic_route_user_intent(body.message)
    except (ValueError, RuntimeError) as e:
        logger.warning("semantic-route LLM 실패, 휴리스틱: %s", e)
        p = semantic_route_fallback(body.message)
    return SemanticRouteResponse(**p)


@router.post("/harness/conflict-resolution", response_model=ConflictResolutionResponse)
async def harness_conflict_resolution(
    body: ConflictResolutionRequest,
) -> ConflictResolutionResponse:
    policy = body.policy or get_settings().graph_conflict_policy
    payload = conflict_resolution_harness(
        body.postgres_status,
        body.graph_status,
        policy=policy,
    )
    return ConflictResolutionResponse(**payload)


@router.get("/graph/ontology")
async def graph_ontology_view() -> dict[str, Any]:
    return graph_ontology()


@router.get("/graph/subgraph/{story_id}", response_model=GraphSubgraphResponse)
async def graph_subgraph_view(
    story_id: uuid.UUID,
    center: str | None = None,
    depth: int = 2,
    limit: int = 120,
    node_types: str | None = None,
) -> GraphSubgraphResponse:
    """3D 지식 그래프 뷰용. node_types 는 쉼표로 구분된 타입 필터(예: "CHAR,LOC")."""
    types_list: list[str] | None = None
    if node_types and node_types.strip():
        types_list = [t.strip() for t in node_types.split(",") if t.strip()]
    try:
        payload = await graph_subgraph(
            story_id,
            center=center,
            depth=depth,
            limit=limit,
            node_types=types_list,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return GraphSubgraphResponse(**payload)


@router.post("/graph-sync/{episode_id}", response_model=GraphSyncResponse)
async def graph_sync_episode(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> GraphSyncResponse:
    r = await db.execute(
        select(Episode).where(Episode.id == episode_id).options(selectinload(Episode.bodies))
    )
    ep = r.scalar_one_or_none()
    if not ep:
        raise HTTPException(404, "episode not found")
    content = full_episode_writing_text(ep).strip()
    if not content:
        raise HTTPException(400, "본문이 비어 있습니다")
    try:
        facts = await extract_graph_facts(content)
        await upsert_graph_facts_to_memory(db, ep.story_id, facts, episode=ep, origin_kind="manual_graph_sync")
        payload = await project_episode_memory_to_graph(db, ep.story_id, ep.id)
        await db.commit()
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return GraphSyncResponse(**payload)


@router.get("/graph/sync-check/{story_id}")
async def graph_sync_check(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    st = await db.get(Story, story_id)
    if not st:
        raise HTTPException(404, "story not found")
    pg_bible = await db.execute(select(StoryBibleEntry).where(StoryBibleEntry.story_id == story_id))
    pg_episodes = await db.execute(select(Episode).where(Episode.story_id == story_id))
    pg_counts = {
        "bible_entries": len(list(pg_bible.scalars().all())),
        "episodes": len(list(pg_episodes.scalars().all())),
    }
    try:
        g_counts = await graph_counts(story_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {
        "postgres": pg_counts,
        "graph": g_counts,
        "balanced_hint": abs(pg_counts["bible_entries"] - g_counts["nodes"]) <= 5,
    }


@router.post("/plan-scenes", response_model=ScenePlanResponse)
async def plan_scenes_route(
    body: ScenePlanRequest,
    db: AsyncSession = Depends(get_db),
) -> ScenePlanResponse:
    ep = await db.get(Episode, body.episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    ctx = await build_writer_context(db, ep.story_id, ep.chapter_num)
    raw = body.raw_memory if body.raw_memory is not None else (ep.raw_memory or "")
    if not raw.strip():
        raise HTTPException(400, "raw_memory 가 비어 있습니다")
    max_scenes = max(1, min(int(body.max_scenes or get_settings().scene_plan_max_scenes), 12))
    try:
        scenes = await plan_scenes(ctx, raw, max_scenes, body.style_axes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"scene_plan 실패: {e}") from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    decision = decide_generation_mode(raw)
    return ScenePlanResponse(scenes=scenes, decision=decision)


@router.post("/memo-qa-survey", response_model=MemoQaSurveyResponse)
async def memo_qa_survey(
    body: MemoQaSurveyRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoQaSurveyResponse:
    ep = await db.get(Episode, body.episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    ctx = await build_writer_context(db, ep.story_id, ep.chapter_num)
    raw = (body.raw_memory if body.raw_memory is not None else (ep.raw_memory or "")) or ""
    if not raw.strip():
        raise HTTPException(400, "raw_memory 가 비어 있어 설문을 만들 수 없습니다")
    decision = decide_generation_mode(raw)
    try:
        segs, questions = await run_memo_qa_survey(ctx, raw, body.style_axes)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    except RuntimeError as e:
        logger.warning("memo-qa-survey LLM 실패: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    items = [MemoSegmentItem(id=s.id, order=s.order, label=s.label, writer_memo=s.writer_memo) for s in segs]
    return MemoQaSurveyResponse(
        decision=decision,
        segments=items,
        questions=questions,
        readiness=assess_memo_readiness(raw, segs, questions, decision),
        estimated_work=estimate_memo_work(segs),
    )


@router.post("/memory-preview", response_model=MemoryPreviewResponse)
async def memory_preview(
    body: MemoryPreviewRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoryPreviewResponse:
    ep = await db.get(Episode, body.episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    bundle = await build_memory_bundle(
        db,
        ep.story_id,
        ep.chapter_num,
        body.segment_memo,
        previous_text=body.previous_text,
        scene_hint=body.scene_hint,
        chapter_state=body.chapter_state,
        limit=body.limit,
    )
    return MemoryPreviewResponse(
        bundle=memory_trace_from_bundle(bundle),
        prompt_block=format_memory_bundle_for_prompt(bundle),
    )


@router.post("/expand-draft", response_model=ExpandDraftResponse)
async def expand_draft(
    body: ExpandDraftRequest,
    db: AsyncSession = Depends(get_db),
) -> ExpandDraftResponse:
    ep = await db.get(Episode, body.episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    ctx = await build_writer_context(db, ep.story_id, ep.chapter_num)
    genre = (body.genre_override or ctx["genre"] or "").strip()
    style_axes = body.style_axes or None
    role = llm.genre_writer_role(genre, ctx.get("style_guide"), style_axes)
    pin = ctx.get("pin", "")
    raw = body.raw_memory if body.raw_memory is not None else (ep.raw_memory or "")
    # world_setting·global_rules 는 system 프롬프트 최상단 Global Context Pin 으로 올라갔으므로
    # 유저 메시지에서는 시놉시스만 남긴다(중복 금지).
    synopsis_block = ctx["synopsis"] or ""

    decision = decide_generation_mode(raw)
    # 씬 플랜 경로는 `use_scene_plan: true` 일 때만 (씬 플란 모달).
    want_scene_plan = bool(body.use_scene_plan)
    if body.multi_step is False:
        want_scene_plan = False
    if want_scene_plan and body.memo_survey is not None:
        raise HTTPException(400, "use_scene_plan 과 memo_survey 는 동시에 사용할 수 없습니다")

    context_used: dict[str, Any] = {
        "synopsis_excerpt": (synopsis_block or "")[:400],
        "bible_excerpt": (ctx["bible_block"] or "")[:1200],
        "graph_excerpt": (ctx.get("graph_block", "") or "")[:1200],
        "prev_summary": ctx["prev_summary"],
        "sliding_window": ctx["sliding"]["combined_for_prompt"][:8000],
        "decision": decision,
        "style_axes": style_axes or {},
        "memory_mode": body.memory_mode,
        "memory_trace": [],
        "sync_trace": [
            {"step": "expand-draft", "status": "server_completed"},
            {"step": "replaceBodies", "status": "client_pending"},
            {"step": "patch raw_memory", "status": "client_pending"},
            {"step": "finalize-episode", "status": "client_pending"},
            {"step": "bible-apply", "status": "client_conditional"},
        ],
    }
    chapter_state: dict[str, Any] = {
        "chapter_num": ep.chapter_num,
        "episode_meta": ep.meta_tags or {},
        "previous_summary": ctx["prev_summary"],
    }

    async def _memory_block_for(
        segment_memo: str,
        *,
        previous_text: str = "",
        scene_hint: str = "",
    ) -> str:
        if body.memory_mode == "off":
            return ""
        bundle = await build_memory_bundle(
            db,
            ep.story_id,
            ep.chapter_num,
            segment_memo,
            previous_text=previous_text,
            scene_hint=scene_hint,
            chapter_state=chapter_state,
        )
        trace = memory_trace_from_bundle(bundle)
        context_used.setdefault("memory_trace", []).append(trace)
        return format_memory_bundle_for_prompt(bundle)

    async def _guard_draft(text: str, source_memo: str, scope: str) -> str:
        try:
            guarded, trace = await revise_draft_if_needed(source_memo, text)
            trace["scope"] = scope
            context_used.setdefault("draft_guard", []).append(trace)
            return guarded
        except Exception as e:
            context_used.setdefault("draft_guard", []).append(
                {"scope": scope, "revision": "error", "error": str(e)[:300]}
            )
            logger.warning("draft fidelity guard 실패(%s): %s", scope, e)
            return text

    async def _record_and_return(
        response: ExpandDraftResponse,
        *,
        run_mode: str,
        segments: list[dict[str, Any]] | None = None,
        revision_payload: dict[str, Any] | None = None,
    ) -> ExpandDraftResponse:
        revision = dict(revision_payload or {})
        revision.setdefault("sync_trace", context_used.get("sync_trace", []))
        revision.setdefault("draft_guard", context_used.get("draft_guard", []))
        row = await record_generation_run(
            db,
            story_id=ep.story_id,
            episode_id=ep.id,
            run_mode=run_mode,
            memory_mode=body.memory_mode,
            segments=segments,
            memory_trace=context_used.get("memory_trace") if isinstance(context_used.get("memory_trace"), list) else [],
            revision_payload=revision,
        )
        response.context_used["generation_run_id"] = str(row.id)
        await db.commit()
        return response

    # ------- 씬 플랜 경로 -------
    if want_scene_plan:
        scenes: list[ScenePlanItem] = list(body.scene_plan or [])
        if not scenes:
            if not raw.strip():
                raise HTTPException(400, "raw_memory 가 비어 있어 씬 플랜을 만들 수 없습니다")
            try:
                max_scenes = get_settings().scene_plan_max_scenes
                scenes = await plan_scenes(ctx, raw, max_scenes, style_axes)
            except ValueError as e:
                # plan 실패 시 single-pass 로 폴백.
                logger.warning("plan_scenes 실패 → single_pass 폴백: %s", e)
                want_scene_plan = False
            except RuntimeError as e:
                logger.warning("plan_scenes LLM 실패 → single_pass 폴백: %s", e)
                want_scene_plan = False

        if want_scene_plan and scenes:
            regen_ids = set(body.regenerate_scene_ids or [])
            # regenerate_scene_ids 가 비면 전부 재생성. 지정됐으면 해당 id 만.
            generated: dict[str, str] = {}
            try:
                for i, scene in enumerate(scenes):
                    target = not regen_ids or scene.id in regen_ids
                    if not target:
                        # 프런트가 기존 본문을 보관하고 재전송/머지하는 책임. 서버는 stateless.
                        generated[scene.id] = ""
                        continue
                    prev_tail, next_hint = build_neighbors(scenes, generated, i)
                    scene_memory = await _memory_block_for(
                        "\n".join(p for p in (scene.goal, scene.hint) if p),
                        previous_text=prev_tail,
                        scene_hint=next_hint,
                    )
                    seg = await write_scene(
                        ctx,
                        scene,
                        prev_tail,
                        next_hint,
                        style_axes=style_axes,
                        genre_override=body.genre_override,
                        memory_block=scene_memory,
                    )
                    scene_source = "\n".join(p for p in (raw, scene.goal, scene.hint) if p)
                    generated[scene.id] = await _guard_draft((seg or "").strip(), scene_source, f"scene:{scene.id}")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            except RuntimeError as e:
                logger.warning("expand-draft 씬 LLM 실패: %s", e)
                raise HTTPException(status_code=502, detail=str(e)) from e

            # 부분 재생성일 때는 빈 문자열 씬이 있으므로 stitch 에서 그 씬을 건너뛴다.
            ordered_parts = [generated.get(s.id, "") for s in scenes if generated.get(s.id, "").strip()]
            settings_s = get_settings()
            if settings_s.scene_stitch_mode == "llm" or len(ordered_parts) > 1:
                stitched = await stitch_with_llm(ordered_parts, ctx, source_memo=raw)
            else:
                stitched = stitch_scenes(ordered_parts)
            stitched = await _guard_draft(stitched, raw, "scene_plan_final")

            scenes_out: list[ExpandedScene] = []
            for s in scenes:
                c = generated.get(s.id, "")
                scenes_out.append(
                    ExpandedScene(
                        scene_id=s.id,
                        content=c,
                        approx_chars=len(c),
                    )
                )
            context_used["generation_mode"] = "scene_plan"
            context_used["segment_count"] = len(scenes)
            context_used["regenerated"] = sorted(regen_ids) if regen_ids else [s.id for s in scenes]
            return await _record_and_return(
                ExpandDraftResponse(
                    ai_content=stitched,
                    context_used=context_used,
                    scenes=scenes_out,
                    scene_plan=scenes,
                ),
                run_mode="scene_plan",
                segments=[s.model_dump() for s in scenes],
                revision_payload={"stitch": "llm" if len(ordered_parts) > 1 else "rule"},
            )

    s_settings = get_settings()
    system = expand_draft_system(pin, genre, role, ctx["style_guide"], ctx["language"])
    prev_max = s_settings.expand_accumulated_prev_max_chars
    max_seg = s_settings.expand_orchestrator_max_segments
    graph_block = str(ctx.get("graph_block", "") or "")
    sliding_full = str(ctx["sliding"]["combined_for_prompt"] or "")

    # 명시 multi_step=True 일 때만 레거시 900자/문단 순차(오케스트 실패 폴백)
    use_multi_fallback = bool(body.multi_step) and not want_scene_plan
    parts = split_draft_for_multi_step(raw) if use_multi_fallback else [raw]
    if use_multi_fallback and len(parts) <= 1:
        use_multi_fallback = False

    async def _one_pass(mem: str) -> str:
        memory_block = await _memory_block_for(mem)
        user = expand_draft_user(
            synopsis_block,
            ctx["bible_block"],
            graph_block,
            memory_block,
            ctx["prev_summary"],
            sliding_full,
            mem,
        )
        return await llm.complete_chat(system, user, temperature=0.55)

    async def _one_pass_from_prev(accum: str, label: str, mem: str) -> str:
        clipped = tail_for_prompt(accum, prev_max)
        memory_block = await _memory_block_for(mem, previous_text=clipped, scene_hint=label)
        user = expand_draft_user_continued(
            synopsis_block,
            ctx["bible_block"],
            graph_block,
            memory_block,
            ctx["prev_summary"],
            sliding_full,
            clipped,
            label,
            mem,
        )
        return await llm.complete_chat(system, user, temperature=0.55)

    def _single_segment_memo(seg: MemoSegment) -> str:
        source = (raw or "").strip()
        memo = (seg.writer_memo or "").strip()
        if not source or source == memo or source in memo:
            return memo
        return f"[원본 작가 메모]\n{source}\n\n[세그먼트 메모]\n{memo}"

    async def _finish_orchestrated(segments: list[MemoSegment], gen_mode: str) -> ExpandDraftResponse:
        if not segments:
            raise HTTPException(400, "세그먼트가 없습니다")
        if len(segments) == 1:
            s0 = segments[0]
            ai_text = (await _one_pass(_single_segment_memo(s0))).strip()
            ai_text = await _guard_draft(ai_text, _single_segment_memo(s0), f"segment:{s0.id}")
            context_used["generation_mode"] = gen_mode
            context_used["segment_count"] = 1
            scenes_out = [
                ExpandedScene(
                    scene_id=s0.id,
                    content=ai_text,
                    approx_chars=len(ai_text),
                    label=s0.label,
                    order=s0.order,
                )
            ]
            return await _record_and_return(
                ExpandDraftResponse(
                    ai_content=ai_text,
                    context_used=context_used,
                    scenes=scenes_out,
                ),
                run_mode=gen_mode,
                segments=[s0.__dict__],
            )
        ai_parts2: list[str] = []
        accumulated2 = ""
        scenes_out2: list[ExpandedScene] = []
        for i, seg in enumerate(segments):
            seg_source = (raw or "").strip() + "\n\n[세그먼트 메모]\n" + (seg.writer_memo or "").strip()
            if i == 0:
                t = (await _one_pass(seg.writer_memo)).strip()
            else:
                t = (await _one_pass_from_prev(accumulated2, seg.label, seg.writer_memo)).strip()
            t = await _guard_draft(t, seg_source, f"segment:{seg.id}")
            ai_parts2.append(t)
            accumulated2 = "\n\n".join(ai_parts2)
            scenes_out2.append(
                ExpandedScene(
                    scene_id=seg.id,
                    content=t,
                    approx_chars=len(t),
                    label=seg.label,
                    order=seg.order,
                )
            )
        source_memo = raw
        if segments:
            source_memo = (raw or "").strip() + "\n\n[세그먼트 원석]\n" + "\n\n".join(
                f"{s.label}\n{s.writer_memo}" for s in segments
            )
        ai_text2 = await stitch_with_llm(ai_parts2, ctx, source_memo=source_memo)
        ai_text2 = await _guard_draft(ai_text2, source_memo, "orchestrated_final")
        context_used["generation_mode"] = gen_mode
        context_used["segment_count"] = len(segments)
        return await _record_and_return(
            ExpandDraftResponse(
                ai_content=ai_text2,
                context_used=context_used,
                scenes=scenes_out2,
            ),
            run_mode=gen_mode,
            segments=[s.__dict__ for s in segments],
            revision_payload={"stitch": "llm", "source_segment_count": len(segments)},
        )

    try:
        if body.memo_survey is not None:
            try:
                merged = apply_memo_qa_answers(
                    body.memo_survey,
                    body.memo_qa_answers,
                )
            except ValueError as e:
                raise HTTPException(400, detail=str(e)) from e
            return await _finish_orchestrated(merged, "orchestrated_draft_memo_qa")

        if body.multi_step is False:
            ai_text = await _one_pass(raw)
            ai_text = await _guard_draft(ai_text, raw, "single_pass")
            context_used["generation_mode"] = "single_pass"
            context_used["segment_count"] = 1
            return await _record_and_return(
                ExpandDraftResponse(ai_content=ai_text, context_used=context_used),
                run_mode="single_pass",
                segments=[{"id": "single", "order": 1, "label": "single_pass", "writer_memo": raw}],
            )

        if decision.get("mode") == "single_pass" and not bool(body.multi_step):
            ai_text = await _one_pass(raw)
            ai_text = await _guard_draft(ai_text, raw, "single_pass")
            context_used["generation_mode"] = "single_pass"
            context_used["segment_count"] = 1
            return await _record_and_return(
                ExpandDraftResponse(ai_content=ai_text, context_used=context_used),
                run_mode="single_pass",
                segments=[{"id": "single", "order": 1, "label": "single_pass", "writer_memo": raw}],
            )

        if not (raw or "").strip():
            raise HTTPException(400, "raw_memory 가 비어 있어 다단계 초안을 쓸 수 없습니다")

        # ----- 메모 오케스트 + 순차 (자동 multi_step 휴리스틱 또는 multi_step 명시) -----
        try:
            segments = await orchestrate_memo_segments(ctx, raw, max_seg, style_axes)
        except (ValueError, RuntimeError) as e:
            logger.warning("orchestrate_memo_segments 실패: %s", e)
            segments = []
        if not segments:
            if use_multi_fallback:
                accumulated = ""
                ai_parts: list[str] = []
                for i, chunk in enumerate(parts):
                    mem = (
                        chunk
                        if i == 0
                        else (
                            "[지금까지 생성된 본문]\n"
                            + accumulated.strip()
                            + "\n\n[다음 장면·메모]\n"
                            + chunk.strip()
                        )
                    )
                    seg = await _one_pass(mem)
                    guarded_seg = await _guard_draft(seg.strip(), chunk, f"fallback-{i + 1}")
                    ai_parts.append(guarded_seg)
                    accumulated = "\n\n".join(ai_parts)
                ai_text = await stitch_with_llm(ai_parts, ctx, source_memo=raw)
                ai_text = await _guard_draft(ai_text, raw, "multi_step_final")
                context_used["generation_mode"] = "multi_step"
                context_used["segment_count"] = len(ai_parts)
                return await _record_and_return(
                    ExpandDraftResponse(ai_content=ai_text, context_used=context_used),
                    run_mode="multi_step",
                    segments=[
                        {"id": f"fallback-{i + 1}", "order": i + 1, "label": f"fallback-{i + 1}", "writer_memo": part}
                        for i, part in enumerate(parts)
                    ],
                    revision_payload={"stitch": "llm", "source_segment_count": len(ai_parts)},
                )
            ai_text = await _one_pass(raw)
            ai_text = await _guard_draft(ai_text, raw, "fallback_single_pass")
            context_used["generation_mode"] = "orchestrated_draft"
            context_used["orchestrator"] = "fallback_single_pass"
            context_used["segment_count"] = 1
            return await _record_and_return(
                ExpandDraftResponse(ai_content=ai_text, context_used=context_used),
                run_mode="orchestrated_draft_fallback_single_pass",
                segments=[{"id": "fallback", "order": 1, "label": "fallback_single_pass", "writer_memo": raw}],
            )

        return await _finish_orchestrated(segments, "orchestrated_draft")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.warning("expand-draft LLM 실패: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        logger.exception("expand-draft 예외")
        raise HTTPException(
            status_code=502,
            detail=f"{type(e).__name__}: {e}",
        ) from e


@router.post("/finalize-episode/{episode_id}")
async def finalize_episode(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    s = get_settings()
    r = await db.execute(
        select(Episode).where(Episode.id == episode_id).options(selectinload(Episode.bodies))
    )
    ep = r.scalar_one_or_none()
    if not ep:
        raise HTTPException(404, "episode not found")
    content = full_episode_writing_text(ep).strip()
    if not content:
        raise HTTPException(400, "본문이 비어 있습니다")
    bodies_sorted = sorted(ep.bodies or [], key=lambda x: x.segment_index)
    texts = [b.content or "" for b in bodies_sorted]
    try:
        hier = await hierarchical_from_block_texts(
            texts,
            paragraph_max_chars=s.hierarchy_block_summary_max_chars,
            chapter_max_chars=s.hierarchy_chapter_summary_max_chars,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    for b, ps in zip(bodies_sorted, hier["paragraph_summaries"]):
        snip = (ps or "").strip()[:4000]
        b.body_summary = snip or None
    ep.summary = (hier.get("chapter_summary") or "")[:2000] or None
    ep.chapter_events = events_for_jsonb(hier.get("events") or [])
    await rag.upsert_chunks_for_episode(
        db,
        ep.story_id,
        ep,
        events=ep.chapter_events or [],
    )
    memory_sync: dict[str, Any] = {"events": 0, "entities": 0, "relationships": 0}
    try:
        event_rows = await upsert_chapter_events_to_memory(db, ep.story_id, ep, ep.chapter_events or [])
        facts = await extract_graph_facts(content)
        fact_counts = await upsert_graph_facts_to_memory(db, ep.story_id, facts, episode=ep)
        memory_sync = {
            "events": len(event_rows),
            "entities": fact_counts.get("entities", 0),
            "relationships": fact_counts.get("relationships", 0),
        }
    except Exception as e:
        logger.warning("canonical memory 동기화 실패(finalize-episode): %s", e)
        memory_sync["error"] = str(e)[:1200]
    try:
        await rollup_story_work_summary(db, ep.story_id, max_chars=s.work_summary_max_chars)
    except (ValueError, RuntimeError) as e:
        logger.warning("작품 전체 요약(rollup) 실패(챕터 요약·청크는 유지): %s", e)
    summary_tree_sync: dict[str, Any] = {"nodes": 0, "stale_cleared": 0, "embedded": 0}
    try:
        summary_tree_sync = await rebuild_episode_summary_tree(db, ep.story_id, ep.id)
    except Exception as e:
        logger.warning("Story-RAPTOR 요약 트리 동기화 실패(finalize-episode): %s", e)
        summary_tree_sync["error"] = str(e)[:1200]
    graph_sync: dict[str, Any] = {"enabled": False, "entities": 0, "relations": 0}
    if s.graph_enabled:
        try:
            graph_sync = await project_episode_memory_to_graph(db, ep.story_id, ep.id)
        except RuntimeError as e:
            logger.warning("Neo4j 동기화 실패(finalize-episode): %s", e)
            # GRAPH_ENABLED 는 켜져 있는데 Neo4j 쓰기만 실패한 경우 — 프론트에서 "꺼짐"과 구분
            graph_sync = {
                "enabled": True,
                "entities": 0,
                "relations": 0,
                "error": str(e)[:1200],
            }
    await db.commit()
    await db.refresh(ep)
    return {
        "summary": ep.summary,
        "chapter_events": ep.chapter_events,
        "chunks_indexed": True,
        "block_summaries_updated": len(bodies_sorted),
        "memory_sync": memory_sync,
        "summary_tree_sync": summary_tree_sync,
        "graph_sync": graph_sync,
    }


@router.post("/bible-extract", response_model=BibleExtractResponse)
async def bible_extract(
    body: BibleExtractRequest,
    db: AsyncSession = Depends(get_db),
) -> BibleExtractResponse:
    ep = await db.get(Episode, body.episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    try:
        raw = await llm.complete_chat_bible(bible_update_system(), bible_update_user(body.ai_content))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    try:
        items = parse_llm_json_array(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"설정 노트 JSON 파싱 실패: {e}") from e
    return BibleExtractResponse(entries=items)


@router.post("/bible-apply/{episode_id}")
async def bible_apply(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    r = await db.execute(
        select(Episode).where(Episode.id == episode_id).options(selectinload(Episode.bodies))
    )
    ep = r.scalar_one_or_none()
    if not ep:
        raise HTTPException(404, "episode not found")
    content = full_episode_writing_text(ep).strip()
    if not content:
        raise HTTPException(400, "본문이 비어 있습니다")
    try:
        raw = await llm.complete_chat_bible(bible_update_system(), bible_update_user(content))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    try:
        items = parse_llm_json_array(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"설정 노트 JSON 파싱 실패: {e}") from e
    rows = _persist_bible_entries(db, ep.story_id, items)
    await db.flush()
    await rag.embed_bible_entries(db, rows)
    memory_entities = await upsert_bible_entries_to_memory(db, ep.story_id, items)
    graph_sync: dict[str, Any] = {"enabled": False, "entities": 0}
    if get_settings().graph_enabled:
        try:
            graph_sync = await project_episode_memory_to_graph(db, ep.story_id, ep.id)
        except RuntimeError as e:
            logger.warning("Neo4j 동기화 실패(bible-apply): %s", e)
            graph_sync = {
                "enabled": True,
                "entities": 0,
                "error": str(e)[:1200],
            }
    await db.commit()
    return {"applied": len(rows), "memory_entities": len(memory_entities), "graph_sync": graph_sync}


@router.post("/bible-commit/{episode_id}")
async def bible_commit(
    episode_id: uuid.UUID,
    body: BibleCommitRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """미리보기(extract) 결과를 그대로 story_bible에 저장. LLM 호출 없음."""
    ep = await db.get(Episode, episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    if not body.entries:
        raise HTTPException(400, "entries is empty")
    rows = _persist_bible_entries(db, ep.story_id, body.entries)
    await db.flush()
    await rag.embed_bible_entries(db, rows)
    memory_entities = await upsert_bible_entries_to_memory(db, ep.story_id, body.entries)
    graph_sync: dict[str, Any] = {"enabled": False, "entities": 0}
    if get_settings().graph_enabled:
        try:
            graph_sync = await project_episode_memory_to_graph(db, ep.story_id, ep.id)
        except RuntimeError as e:
            logger.warning("Neo4j 동기화 실패(bible-commit): %s", e)
            graph_sync = {
                "enabled": True,
                "entities": 0,
                "error": str(e)[:1200],
            }
    await db.commit()
    return {"applied": len(rows), "memory_entities": len(memory_entities), "graph_sync": graph_sync}


@router.post("/bridge", response_model=BridgeResponse)
async def bridge_suggest(
    body: BridgeRequest,
    db: AsyncSession = Depends(get_db),
) -> BridgeResponse:
    hint = ""
    pin = ""
    if body.story_id:
        entries = await fetch_bible(db, body.story_id)
        hint = format_bible(entries, limit=25)
        story = await db.get(Story, body.story_id)
        if story:
            pin_ctx = {
                "title": story.title or "",
                "genre": story.genre or "",
                "world_setting": (story.world_setting or "").strip(),
                "global_rules": story.global_rules,
                "style_guide": story.style_guide or "",
                "language": story.language or "KO",
            }
            pin = format_global_context_pin(pin_ctx)
    text = await llm.complete_chat(
        bridge_system(pin),
        bridge_user(
            body.summary_a,
            body.raw_memory_b,
            hint,
            body.anchor_excerpt or "",
        ),
        temperature=0.6,
    )
    return BridgeResponse(suggestions=text)


@router.post("/rag-search", response_model=list[RAGSearchResult])
async def rag_search(
    body: RAGSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> list[RAGSearchResult]:
    st = await db.get(Story, body.story_id)
    if not st:
        raise HTTPException(404, "story not found")
    summary_hits = await search_summary_nodes(db, body.story_id, body.query, limit=body.limit)
    summary_results = [
        RAGSearchResult(
            source_type="summary",
            summary_node_id=uuid.UUID(hit.id),
            summary_node_key=hit.node_key,
            summary_level=hit.level,
            chapter_num=hit.chapter_start or 0,
            snippet=hit.summary[:1200],
            score=hit.score,
            heatmap_bucket=heatmap_bucket_from_score(hit.score),
        )
        for hit in summary_hits
    ]
    merged = await rag.search_rag_merged(db, body.story_id, body.query, body.limit)
    if not merged:
        out: list[RAGSearchResult] = list(summary_results)
        for ep, snip in await rag.keyword_fallback_episodes(db, body.story_id, body.query, body.limit):
            out.append(
                RAGSearchResult(
                    source_type="episode",
                    episode_id=ep.id,
                    chapter_num=ep.chapter_num,
                    snippet=snip,
                    score=None,
                )
            )
        for ent, snip in await rag.keyword_fallback_bible(db, body.story_id, body.query, body.limit):
            out.append(
                RAGSearchResult(
                    source_type="bible",
                    bible_entry_id=ent.id,
                    snippet=snip,
                    score=None,
                )
            )
        out.sort(key=lambda row: (row.score is None, -(row.score or 0.0)))
        return out[: body.limit]

    def _safe_int_meta(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    results: list[RAGSearchResult] = list(summary_results)
    for src, obj, score, snip, eid, chnum in merged:
        if src == "episode" and isinstance(obj, EpisodeChunk):
            meta = obj.chunk_meta if isinstance(obj.chunk_meta, dict) else {}
            ct = meta.get("color_tag")
            pe_id = meta.get("parent_event_id")
            pe_title = meta.get("parent_event_title")
            results.append(
                RAGSearchResult(
                    source_type="episode",
                    chunk_id=obj.id,
                    episode_id=eid,
                    chapter_num=chnum,
                    snippet=snip,
                    score=score,
                    category=obj.category,
                    color_tag=ct if isinstance(ct, str) else None,
                    segment_index=_safe_int_meta(meta.get("segment_index")),
                    paragraph_index=_safe_int_meta(meta.get("paragraph_index")),
                    heatmap_bucket=heatmap_bucket_from_score(score),
                    parent_event_id=pe_id if isinstance(pe_id, str) else None,
                    parent_event_title=pe_title if isinstance(pe_title, str) else None,
                )
            )
        elif src == "bible" and isinstance(obj, StoryBibleEntry):
            results.append(
                RAGSearchResult(
                    source_type="bible",
                    bible_entry_id=obj.id,
                    snippet=snip,
                    score=score,
                    heatmap_bucket=heatmap_bucket_from_score(score),
                )
            )
    results.sort(key=lambda row: (row.score is None, -(row.score or 0.0)))
    return results[: body.limit]


@router.get("/event-map/{episode_id}", response_model=EventMapResponse)
async def event_map(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EventMapResponse:
    """챕터 이벤트와 paragraph chunk 를 parent-child 로 묶어 반환한다."""
    r = await db.execute(select(Episode).where(Episode.id == episode_id))
    ep = r.scalar_one_or_none()
    if not ep:
        raise HTTPException(404, "episode not found")
    events = ep.chapter_events if isinstance(ep.chapter_events, list) else []
    r2 = await db.execute(
        select(EpisodeChunk)
        .where(EpisodeChunk.episode_id == episode_id)
        .order_by(EpisodeChunk.chunk_index.asc())
    )
    chunks = list(r2.scalars().all())

    def _meta(ch: EpisodeChunk) -> dict[str, Any]:
        return ch.chunk_meta if isinstance(ch.chunk_meta, dict) else {}

    def _safe_int(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    chunk_dicts: list[dict[str, Any]] = []
    for ch in chunks:
        m = _meta(ch)
        pe_id = m.get("parent_event_id")
        chunk_dicts.append(
            {
                "id": ch.id,
                "segment_index": _safe_int(m.get("segment_index")),
                "paragraph_index": _safe_int(m.get("paragraph_index")),
                "snippet": (ch.content or "")[:600],
                "category": ch.category,
                "color_tag": m.get("color_tag") if isinstance(m.get("color_tag"), str) else None,
                "parent_event_id": pe_id if isinstance(pe_id, str) else None,
            }
        )

    mapping_rows = build_event_map(events, chunk_dicts)
    entries: list[EventMapEntry] = []
    for row in mapping_rows:
        refs: list[EventMapChunkRef] = [
            EventMapChunkRef(
                chunk_id=uuid.UUID(str(x["id"])) if not isinstance(x["id"], uuid.UUID) else x["id"],
                segment_index=x.get("segment_index"),
                paragraph_index=x.get("paragraph_index"),
                snippet=x.get("snippet") or "",
                category=x.get("category"),
                color_tag=x.get("color_tag"),
            )
            for x in row.get("refs") or []
        ]
        entries.append(
            EventMapEntry(
                event_id=row["event_id"],
                title=row["title"],
                cause=row.get("cause", ""),
                outcome=row.get("outcome", ""),
                turning_point=row.get("turning_point", ""),
                stakes=row.get("stakes", ""),
                ref_count=len(refs),
                refs=refs,
            )
        )
    orphan = [
        EventMapChunkRef(
            chunk_id=x["id"] if isinstance(x["id"], uuid.UUID) else uuid.UUID(str(x["id"])),
            segment_index=x.get("segment_index"),
            paragraph_index=x.get("paragraph_index"),
            snippet=x.get("snippet") or "",
            category=x.get("category"),
            color_tag=x.get("color_tag"),
        )
        for x in chunk_dicts
        if not x.get("parent_event_id")
    ]
    return EventMapResponse(
        episode_id=episode_id,
        chapter_num=ep.chapter_num,
        events=entries,
        orphan_chunks=orphan,
    )


@router.post("/consistency", response_model=ConsistencyResponse)
async def consistency_check(
    body: ConsistencyRequest,
    db: AsyncSession = Depends(get_db),
) -> ConsistencyResponse:
    story, episodes = await load_story_episodes(db, body.story_id)
    bible = await fetch_bible(db, body.story_id)
    bible_txt = format_bible(bible, limit=80)
    pin_ctx = {
        "title": story.title or "",
        "genre": story.genre or "",
        "world_setting": (story.world_setting or "").strip(),
        "global_rules": story.global_rules,
        "style_guide": story.style_guide or "",
        "language": story.language or "KO",
    }
    pin = format_global_context_pin(pin_ctx)
    if body.focus_episode_id:
        r = await db.execute(
            select(Episode)
            .where(Episode.id == body.focus_episode_id, Episode.story_id == body.story_id)
            .options(selectinload(Episode.bodies))
        )
        ep = r.scalar_one_or_none()
        if not ep:
            raise HTTPException(404, "focus episode not found")
        blob = (full_episode_writing_text(ep) or ep.raw_memory or "").strip()
        if len(blob) > 14000:
            blob = blob[:14000] + "\n…(이하 생략)"
        label = f"챕터 {ep.chapter_num}"
        report = await llm.complete_chat(
            consistency_focus_system(pin),
            consistency_focus_user(story.synopsis or "", bible_txt, label, blob),
            temperature=0.2,
        )
        return ConsistencyResponse(report=report)
    parts: list[str] = []
    for e in sorted(episodes, key=lambda x: x.chapter_num)[-12:]:
        blob = (full_episode_writing_text(e) or e.raw_memory or "")[:3500]
        parts.append(f"챕터 {e.chapter_num}:\n{blob}")
    report = await llm.complete_chat(
        consistency_system(pin),
        consistency_user(story.synopsis or "", bible_txt, "\n\n".join(parts)),
        temperature=0.2,
    )
    return ConsistencyResponse(report=report)


@router.post("/style-transfer", response_model=StyleTransferResponse)
async def style_transfer(body: StyleTransferRequest) -> StyleTransferResponse:
    out = await llm.complete_chat(
        style_transfer_system(body.target_style),
        style_transfer_user(body.text),
        temperature=0.65,
    )
    return StyleTransferResponse(text=out)


@router.post("/export")
async def export_story(
    body: ExportRequest,
    db: AsyncSession = Depends(get_db),
) -> Response:
    story, full = await build_story_text(db, body.story_id)
    fmt = (body.format or "txt").lower()
    if fmt == "txt":
        data = to_txt_bytes(full)
        media = "text/plain; charset=utf-8"
        ext = "txt"
    elif fmt == "pdf":
        try:
            data = to_pdf_bytes(story.title, full)
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        media = "application/pdf"
        ext = "pdf"
    elif fmt == "epub":
        data = to_epub_bytes(story.title, full)
        media = "application/epub+zip"
        ext = "epub"
    else:
        raise HTTPException(400, "format must be txt, pdf, or epub")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in story.title)[:80]
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.{ext}"'},
    )


@router.get("/context-preview/{story_id}")
async def context_preview(
    story_id: uuid.UUID,
    chapter_num: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ctx = await build_writer_context(db, story_id, chapter_num)
    return ctx
