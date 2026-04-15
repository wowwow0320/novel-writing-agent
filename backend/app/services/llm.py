import asyncio
import logging
from typing import Any

import google.api_core.exceptions
import httpx
import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory
from openai import APIError, AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

# 소설 생성은 기본 안전 필터에 걸리기 쉬워, 높은 위험도만 차단
_GEMINI_SAFETY = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
}


def _gemini_model_name(raw: str) -> str:
    name = (raw or "gemini-2.0-flash").strip()
    if name.startswith("models/"):
        name = name.removeprefix("models/")
    return name


async def complete_chat(system: str, user: str, temperature: float = 0.75) -> str:
    s = get_settings()
    if s.ai_provider == "openai":
        if not (s.openai_api_key or "").strip():
            raise ValueError("OPENAI_API_KEY가 비어 있습니다. backend/.env 또는 Docker 루트 .env를 확인하세요.")
        client = AsyncOpenAI(api_key=s.openai_api_key)
        try:
            r = await client.chat.completions.create(
                model=s.openai_model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except APIError as e:
            raise RuntimeError(f"OpenAI API 오류 (model={s.openai_model}): {e}") from e
        return (r.choices[0].message.content or "").strip()

    key = (s.gemini_api_key or "").strip()
    if not key:
        raise ValueError(
            "GEMINI_API_KEY가 비어 있습니다. backend/.env(로컬) 또는 프로젝트 루트 .env(Docker)에 키를 넣고 백엔드를 재시작하세요."
        )

    model_name = _gemini_model_name(s.gemini_model)
    gen_cfg: dict[str, Any] = {"temperature": temperature}

    def _gemini_sync_call() -> str:
        genai.configure(api_key=key)
        m = genai.GenerativeModel(
            model_name,
            system_instruction=system,
        )
        resp = m.generate_content(
            user,
            generation_config=gen_cfg,
            safety_settings=_GEMINI_SAFETY,
        )
        try:
            return (resp.text or "").strip()
        except ValueError as ve:
            fb = getattr(resp, "prompt_feedback", None)
            raise RuntimeError(
                f"Gemini가 본문을 반환하지 않았습니다. model={model_name}. "
                f"prompt_feedback={fb}. 원인: {ve}"
            ) from ve

    genai.configure(api_key=key)
    model = genai.GenerativeModel(
        model_name,
        system_instruction=system,
    )
    try:
        r = await model.generate_content_async(
            user,
            generation_config=gen_cfg,
            safety_settings=_GEMINI_SAFETY,
        )
    except google.api_core.exceptions.GoogleAPIError as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err or "Resource exhausted" in err:
            raise RuntimeError(
                "Gemini 할당량 초과(429). backend/.env 에서 AI_PROVIDER=openai 로 설정하고 "
                "OPENAI_API_KEY 를 넣은 뒤 백엔드를 재시작하세요."
            ) from e
        logger.warning("Gemini async 실패, 동기 호출로 재시도: %s", e)
        try:
            text = await asyncio.to_thread(_gemini_sync_call)
        except Exception as e2:
            raise RuntimeError(
                f"Gemini API 실패 (model={model_name}). async: {e} | sync: {e2}"
            ) from e2
        if not text:
            raise RuntimeError(f"Gemini 응답이 비어 있습니다. model={model_name}")
        return text

    try:
        text = (r.text or "").strip()
    except ValueError as e:
        fb = getattr(r, "prompt_feedback", None)
        logger.warning("Gemini async 응답 text 파싱 실패, 동기 재시도: %s", e)
        try:
            text = await asyncio.to_thread(_gemini_sync_call)
        except Exception as e2:
            raise RuntimeError(
                f"Gemini가 본문을 반환하지 않았습니다. model={model_name}. "
                f"prompt_feedback={fb}. async_err={e} | sync_err={e2}"
            ) from e2

    if not text:
        try:
            text = await asyncio.to_thread(_gemini_sync_call)
        except Exception as se:
            raise RuntimeError(
                f"Gemini 응답이 비어 있습니다. model={model_name}. 동기 재시도: {se}"
            ) from se
    return text


def _parse_ollama_embed_response(data: dict[str, Any]) -> list[list[float]]:
    if "embeddings" in data and data["embeddings"]:
        return [list(x) for x in data["embeddings"]]
    emb = data.get("embedding")
    if emb is not None:
        return [list(emb)]
    return []


async def _ollama_embed_batches(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    base = (s.ollama_base_url or "").rstrip("/")
    model = (s.ollama_embed_model or "bge-m3").strip()
    batch_n = max(1, min(64, s.ollama_embed_batch_size))
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(0, len(texts), batch_n):
            batch = texts[i : i + batch_n]
            r = await client.post(
                f"{base}/api/embed",
                json={"model": model, "input": batch},
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"Ollama 임베딩 실패 HTTP {r.status_code}: {r.text[:500]}. "
                    f"base={base} model={model} (ollama pull {model} 확인)"
                )
            parsed = _parse_ollama_embed_response(r.json())
            if len(parsed) != len(batch):
                raise RuntimeError(
                    f"Ollama 임베딩 개수 불일치: 요청 {len(batch)}건, 응답 {len(parsed)}건 (model={model})"
                )
            for j, vec in enumerate(parsed):
                if len(vec) != s.embedding_dimension:
                    raise RuntimeError(
                        f"임베딩 벡터 차원이 {len(vec)}인데 EMBEDDING_DIMENSION={s.embedding_dimension} 입니다. "
                        f"bge-m3는 보통 1024 — .env 와 Alembic 벡터 컬럼 차원을 맞추세요."
                    )
                out.append(vec)
    return out


async def embed_texts(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    if s.embedding_provider == "none" or not texts:
        return []
    if s.embedding_provider == "ollama":
        return await _ollama_embed_batches(texts)
    if s.embedding_provider == "openai":
        client = AsyncOpenAI(api_key=s.openai_api_key or None)
        r = await client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
            dimensions=s.embedding_dimension,
        )
        return [d.embedding for d in r.data]
    genai.configure(api_key=s.gemini_api_key)
    out: list[list[float]] = []
    for t in texts:
        r = genai.embed_content(
            model="models/text-embedding-004",
            content=t,
            task_type="retrieval_document",
        )
        emb = r.get("embedding")
        if emb is None and isinstance(r, dict):
            emb = r.get("embedding", [])
        vec = list(emb) if emb else []
        if vec and len(vec) != s.embedding_dimension:
            raise RuntimeError(
                f"Gemini text-embedding-004 출력 차원({len(vec)})이 EMBEDDING_DIMENSION={s.embedding_dimension}과 "
                "다릅니다. bge-m3(1024) 기본 스택에는 EMBEDDING_PROVIDER=ollama 또는 openai를 쓰세요."
            )
        out.append(vec)
    return out


def genre_writer_role(genre: str) -> str:
    g = (genre or "").strip().lower()
    mapping: dict[str, str] = {
        "로맨스": "로맨스 소설 작가",
        "romance": "로맨스 소설 작가",
        "스릴러": "스릴러·미스터리 소설 작가",
        "thriller": "스릴러·미스터리 소설 작가",
        "판타지": "판타지 소설 작가",
        "fantasy": "판타지 소설 작가",
        "sf": "SF 소설 작가",
        "공상과학": "SF 소설 작가",
        "역사": "역사 소설 작가",
        "historical": "역사 소설 작가",
        "문학": "문학 소설가",
        "literary": "문학 소설가",
    }
    for key, role in mapping.items():
        if key in g:
            return role
    return "장편 소설 작가"
