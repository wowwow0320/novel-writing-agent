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
from app.models import BibleCategory, Episode, EpisodeChunk, Story, StoryBibleEntry
from app.schemas import (
    BibleCommitRequest,
    BibleExtractRequest,
    BibleExtractResponse,
    BridgeRequest,
    BridgeResponse,
    ConsistencyRequest,
    ConsistencyResponse,
    ExpandDraftRequest,
    ExpandDraftResponse,
    ExportRequest,
    RAGSearchRequest,
    RAGSearchResult,
    StyleTransferRequest,
    StyleTransferResponse,
)
from app.services import llm, rag
from app.services.episode_text import full_episode_writing_text
from app.services.context_builder import build_writer_context, fetch_bible, format_bible, load_story_episodes
from app.services.export import build_story_text, to_epub_bytes, to_pdf_bytes, to_txt_bytes
from app.services.json_extract import parse_llm_json_array
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
    style_transfer_system,
    style_transfer_user,
    summary_system,
    summary_user,
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
    role = llm.genre_writer_role(genre)
    system = expand_draft_system(genre, role, ctx["style_guide"], ctx["language"])
    raw = body.raw_memory if body.raw_memory is not None else (ep.raw_memory or "")
    user = expand_draft_user(
        ctx["synopsis"],
        ctx["bible_block"],
        ctx["prev_summary"],
        ctx["sliding"]["combined_for_prompt"],
        raw,
    )
    try:
        ai_text = await llm.complete_chat(system, user)
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
    payload = {
        "synopsis_excerpt": (ctx["synopsis"] or "")[:400],
        "bible_excerpt": (ctx["bible_block"] or "")[:1200],
        "prev_summary": ctx["prev_summary"],
        "sliding_window": ctx["sliding"]["combined_for_prompt"][:8000],
    }
    return ExpandDraftResponse(ai_content=ai_text, context_used=payload)


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
    sys_p = summary_system(s.summary_max_chars)
    summ = await llm.complete_chat(sys_p, summary_user(content))
    ep.summary = summ[:2000]
    await rag.upsert_chunks_for_episode(db, ep.story_id, ep)
    await db.commit()
    await db.refresh(ep)
    return {"summary": ep.summary, "chunks_indexed": True}


@router.post("/bible-extract", response_model=BibleExtractResponse)
async def bible_extract(
    body: BibleExtractRequest,
    db: AsyncSession = Depends(get_db),
) -> BibleExtractResponse:
    ep = await db.get(Episode, body.episode_id)
    if not ep:
        raise HTTPException(404, "episode not found")
    raw = await llm.complete_chat(bible_update_system(), bible_update_user(body.ai_content))
    items = parse_llm_json_array(raw)
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
    raw = await llm.complete_chat(bible_update_system(), bible_update_user(content))
    items = parse_llm_json_array(raw)
    rows = _persist_bible_entries(db, ep.story_id, items)
    await db.flush()
    await rag.embed_bible_entries(db, rows)
    await db.commit()
    return {"applied": len(rows)}


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
    await db.commit()
    return {"applied": len(rows)}


@router.post("/bridge", response_model=BridgeResponse)
async def bridge_suggest(
    body: BridgeRequest,
    db: AsyncSession = Depends(get_db),
) -> BridgeResponse:
    hint = ""
    if body.story_id:
        entries = await fetch_bible(db, body.story_id)
        hint = format_bible(entries, limit=25)
    text = await llm.complete_chat(
        bridge_system(),
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
    merged = await rag.search_rag_merged(db, body.story_id, body.query, body.limit)
    if not merged:
        out: list[RAGSearchResult] = []
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
        return out[: body.limit]
    results: list[RAGSearchResult] = []
    for src, obj, score, snip, eid, chnum in merged:
        if src == "episode" and isinstance(obj, EpisodeChunk):
            results.append(
                RAGSearchResult(
                    source_type="episode",
                    chunk_id=obj.id,
                    episode_id=eid,
                    chapter_num=chnum,
                    snippet=snip,
                    score=score,
                )
            )
        elif src == "bible" and isinstance(obj, StoryBibleEntry):
            results.append(
                RAGSearchResult(
                    source_type="bible",
                    bible_entry_id=obj.id,
                    snippet=snip,
                    score=score,
                )
            )
    return results


@router.post("/consistency", response_model=ConsistencyResponse)
async def consistency_check(
    body: ConsistencyRequest,
    db: AsyncSession = Depends(get_db),
) -> ConsistencyResponse:
    story, episodes = await load_story_episodes(db, body.story_id)
    bible = await fetch_bible(db, body.story_id)
    bible_txt = format_bible(bible, limit=80)
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
            consistency_focus_system(),
            consistency_focus_user(story.synopsis or "", bible_txt, label, blob),
            temperature=0.2,
        )
        return ConsistencyResponse(report=report)
    parts: list[str] = []
    for e in sorted(episodes, key=lambda x: x.chapter_num)[-12:]:
        blob = (full_episode_writing_text(e) or e.raw_memory or "")[:3500]
        parts.append(f"챕터 {e.chapter_num}:\n{blob}")
    report = await llm.complete_chat(
        consistency_system(),
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
