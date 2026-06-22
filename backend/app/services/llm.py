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


def _openai_model_only_default_temperature(model: str) -> bool:
    """일부 추론·nano 계열은 API에서 temperature=1(기본)만 허용."""
    m = (model or "").strip().lower()
    if m.startswith("gpt-5"):
        return True
    if m.startswith(("o1", "o3", "o4")):
        return True
    return False


async def complete_chat_bible(system: str, user: str, temperature: float = 0.2) -> str:
    """스토리 바이블 추출·갱신 전용. OpenAI 키가 있으면 `OPENAI_BIBLE_MODEL`(기본 gpt-5-nano)로 호출."""
    s = get_settings()
    if (s.openai_api_key or "").strip():
        model = (s.openai_bible_model or "gpt-5-nano").strip()
        client = AsyncOpenAI(api_key=s.openai_api_key)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        fixed_temp = _openai_model_only_default_temperature(model)
        temp_kw: float = 1.0 if fixed_temp else temperature
        try:
            r = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temp_kw,
            )
        except APIError as e:
            # 목록에 없는 모델이 동일 제약일 때만 한 번 재시도
            err_low = str(e).lower()
            if (
                not fixed_temp
                and "temperature" in err_low
                and (getattr(e, "status_code", None) == 400 or "unsupported_value" in err_low)
            ):
                logger.warning(
                    "바이블 모델 %s 가 temperature=%s 미지원, temperature=1 로 재시도: %s",
                    model,
                    temperature,
                    e,
                )
                try:
                    r = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=1,
                    )
                except APIError as e2:
                    raise RuntimeError(f"OpenAI 바이블 추출 오류 (model={model}): {e2}") from e2
            else:
                raise RuntimeError(f"OpenAI 바이블 추출 오류 (model={model}): {e}") from e
        return (r.choices[0].message.content or "").strip()
    return await complete_chat(system, user, temperature)


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
        if not (s.openai_api_key or "").strip():
            raise ValueError(
                "EMBEDDING_PROVIDER=openai 인데 OPENAI_API_KEY가 비어 있습니다. "
                "루트 또는 backend/.env에 키를 넣고 백엔드를 재시작하세요."
            )
        model = (s.openai_embed_model or "text-embedding-3-large").strip()
        client = AsyncOpenAI(api_key=s.openai_api_key)
        r = await client.embeddings.create(
            model=model,
            input=texts,
            dimensions=s.embedding_dimension,
        )
        vecs = [d.embedding for d in r.data]
        for i, vec in enumerate(vecs):
            if vec and len(vec) != s.embedding_dimension:
                raise RuntimeError(
                    f"OpenAI 임베딩 차원이 {len(vec)}인데 EMBEDDING_DIMENSION={s.embedding_dimension} 입니다. "
                    f"model={model} — .env 의 EMBEDDING_DIMENSION 과 DB(pgvector) 컬럼 차원을 맞추세요."
                )
        return vecs
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


_STYLE_AXES_LENGTH = {
    "short": "응축된 문장",
    "mid": "보통 길이의 문장",
    "long": "만연체·장면 묘사를 길게 풀어내는",
}
_STYLE_AXES_REGISTER = {
    "colloquial": "구어체·회화적",
    "literary": "문어체·문학적",
}
_STYLE_AXES_RHYTHM = {
    "staccato": "짧게 끊어지는 리듬의",
    "flowing": "유려하게 흐르는 리듬의",
}


def genre_writer_role(
    genre: str,
    style_guide: str | None = None,
    style_axes: dict[str, str] | None = None,
) -> str:
    """장르 + (선택) style_guide + (선택) style_axes 로 역할 문자열을 만든다.

    우선순위는 `style_guide > style_axes > genre 기본값` (docs/pipeline/02 §4.3).
    style_guide 가 비어있을 때만 style_axes 가 반영된다.
    """
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
        "호러": "호러·공포 소설 작가",
        "horror": "호러·공포 소설 작가",
        "무협": "무협·무사극 소설 작가",
        "라이트": "라이트노벨 톤의 소설 작가",
        "light": "라이트노벨 톤의 소설 작가",
    }
    base = "장편 소설 작가"
    for key, role in mapping.items():
        if key in g:
            base = role
            break
    sg = (style_guide or "").strip()
    if sg:
        low = sg.lower()
        voice: list[str] = []
        if any(x in low for x in ["서정", "감성", "lyric"]):
            voice.append("서정적")
        if any(x in low for x in ["건조", "dry", "간결"]):
            voice.append("건조하고 간결한")
        if any(x in low for x in ["유머", "코믹", "wit"]):
            voice.append("유머러스한")
        if any(x in low for x in ["냉소", "ironic", "아이러니"]):
            voice.append("냉소적")
        if any(x in low for x in ["속도감", "fast", "스릴"]):
            voice.append("속도감 있는")
        if voice:
            return base + f"({', '.join(voice)} 문체 축)"
        return base

    if not style_axes:
        return base
    axes_voice: list[str] = []
    length = str(style_axes.get("length", "")).strip().lower()
    register = str(style_axes.get("register", "")).strip().lower()
    rhythm = str(style_axes.get("rhythm", "")).strip().lower()
    for key, table in (
        (length, _STYLE_AXES_LENGTH),
        (register, _STYLE_AXES_REGISTER),
        (rhythm, _STYLE_AXES_RHYTHM),
    ):
        v = table.get(key)
        if v:
            axes_voice.append(v)
    if axes_voice:
        return base + f"({', '.join(axes_voice)} 문체)"
    return base
