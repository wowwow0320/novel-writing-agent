import asyncio
import json
import logging
import re
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import StoryEntity, StoryEvent, StoryRelationship, StorySummaryNode
from app.services import llm

logger = logging.getLogger(__name__)

# Neo4j 동기화·LLM 입력 상한 (초과분은 앞/뒤를 유지하고 중간 생략)
GRAPH_EXTRACT_TEXT_MAX = 18_000

# Graph ontology (초기 버전)
GRAPH_NODE_TYPES = {"CHAR", "LOC", "EVENT", "ITEM", "ORG", "SITUATION", "SUMMARY"}
GRAPH_RELATION_TYPES = {
    "ALLY_OF",
    "ENEMY_OF",
    "FAMILY_OF",
    "LOVES",
    "BELONGS_TO",
    "LOCATED_IN",
    "PARTICIPATED_IN",
    "CAUSES",
    "AFTER",
    "BEFORE",
    "DIED_IN",
    "TRIGGERED_BY",
    "LEADS_TO",
    "INVOLVED_IN",
    "HAS_SUMMARY",
    "SUMMARIZES",
    "MENTIONS_ENTITY",
    "COVERS_EVENT",
}


class Neo4jHttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or []

# 모델이 흔히 쓰는 비표준 라벨 → 스키마 값
_RELATION_ALIASES: dict[str, str] = {
    "PARTICIPATES": "PARTICIPATED_IN",
    "PARTICIPATE": "PARTICIPATED_IN",
    "PARTICIPATION": "PARTICIPATED_IN",
    "LOCATED": "LOCATED_IN",
    "LOCATION": "LOCATED_IN",
    "AT": "LOCATED_IN",
    "IN": "LOCATED_IN",
    "LOVE": "LOVES",
    "FAMILY": "FAMILY_OF",
    "ALLY": "ALLY_OF",
    "ENEMY": "ENEMY_OF",
    "MEMBER_OF": "BELONGS_TO",
    "PART_OF": "BELONGS_TO",
    "OWNS": "BELONGS_TO",
    "CAUSE": "CAUSES",
    "RESULTS_IN": "LEADS_TO",
    "LEADS": "LEADS_TO",
    "TRIGGER": "TRIGGERED_BY",
    "INVOLVED": "INVOLVED_IN",
    "INVOLVES": "INVOLVED_IN",
    "RELATED_TO": "INVOLVED_IN",
    "INTERACTS_WITH": "INVOLVED_IN",
    "MEETS": "INVOLVED_IN",
    "KNOWS": "INVOLVED_IN",
}


def graph_ontology() -> dict[str, Any]:
    return {
        "node_types": sorted(GRAPH_NODE_TYPES),
        "relation_types": sorted(GRAPH_RELATION_TYPES),
    }


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def relation_extract_system() -> str:
    o = graph_ontology()
    rels = ", ".join(o["relation_types"])
    nodes = ", ".join(o["node_types"])
    return f"""당신은 소설 지식 그래프(Neo4j)용 관계 추출기입니다.
아래 본문만 보고, 나중에 Cypher MERGE (a:Entity)-[:RELATES]->(b:Entity) 로 넣을 JSON을 만듭니다.

## 노드 타입 (정확히 이 문자열만)
{nodes}
- SITUATION: 장면·분위기·정황 단위(예: "한밤중 폐창고", "협상 테이블")

## 관계 타입 (정확히 이 문자열만, 대문자+밑줄)
{rels}
- 등장·대화·같은 사건에 같이 있음 → INVOLVED_IN 또는 PARTICIPATED_IN
- 장소 안에 있음 → LOCATED_IN (인물→장소)
- 소속·소지 → BELONGS_TO
- 적대·연인·가족 등은 의미에 맞게 ENEMY_OF / LOVES / FAMILY_OF 등

## 반드시 지킬 것
1) JSON **객체 하나**만 출력 (설명·마크다운 금지).
2) **relations 배열을 비우지 마세요.** 본문에 인물·장소가 2명(곳) 이상이면 **최소 4개**의 관계 객체를 채웁니다. 근거가 약하면 confidence를 낮추되(0.35~0.55), 그래도 엣지는 만듭니다.
3) 각 relation의 subject/object 문자열은 **entities에 나온 name과 완전히 동일**해야 합니다(별칭 금지).
4) entities에는 본문에 실제로 나오는 이름 위주로 8~40개 정도. 너무 적으면 관계를 못 만들므로 과하지 않게 풍부히.
5) relation 필드는 허용 목록 외 값이면 안 됩니다.

## 출력 스키마
{{
  "entities": [{{"name":"…","type":"CHAR|…","status":"alive|dead|unknown","origin_hint":"한 줄 근거","importance":1-5}}],
  "relations": [
    {{"subject":"…","subject_type":"CHAR","relation":"INVOLVED_IN","object":"…","object_type":"CHAR","context":"근거 한 줄","confidence":0.55}}
  ]
}}"""


def relation_extract_user(text: str) -> str:
    return f"""[본문 — 그래프 추출용]
{text}
"""


def relation_extract_pass2_system() -> str:
    o = graph_ontology()
    return f"""이전 단계에서 relations가 비었습니다. 이번에는 **관계(relations)만** 채우세요.

규칙:
- 출력은 JSON 객체 하나: {{"relations": [...]}}
- relations에는 **최소 6개**, 최대 40개 항목.
- subject/object는 아래에 주어진 **엔티티 이름과 문자 단위로 동일**해야 합니다.
- relation은 반드시 다음 중 하나: {", ".join(o["relation_types"])}
- 본문에 함께 등장·대화·같은 사건이면 INVOLVED_IN 또는 PARTICIPATED_IN을 우선 사용.
- 장소·조직과의 연결에는 LOCATED_IN, BELONGS_TO 등을 사용.
- 출력 외 텍스트 금지."""


def relation_extract_pass2_user(entities: list[dict[str, Any]], text: str) -> str:
    lines = []
    for e in entities:
        n = str(e.get("name", "")).strip()
        if not n:
            continue
        t = _normalize_type(e.get("type"), "CHAR")
        lines.append(f"- {n} ({t})")
    ent_block = "\n".join(lines) if lines else "(없음)"
    return f"""[엔티티 목록 — subject/object는 아래 이름만 사용]
{ent_block}

[본문]
{text}
"""


def graph_to_text_system(limit: int) -> str:
    return f"""당신은 그래프 구조를 소설 생성 컨텍스트로 바꾸는 편집자입니다.
주어진 관계 목록에서 최대 {limit}개 핵심 관계를 자연어 bullet로 바꿔주세요.
충돌·사망 상태·적대 관계를 우선해 간결히 작성합니다."""


def graph_to_text_user(lines: str) -> str:
    return f"""[그래프 관계 원문]
{lines}
"""


def _normalize_type(raw: Any, fallback: str) -> str:
    t = str(raw or fallback).strip().upper()
    if t in GRAPH_NODE_TYPES:
        return t
    if t in ("SCENE", "MOOD"):
        return "SITUATION"
    return fallback


def _normalize_relation(raw: Any) -> str:
    r = str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")
    r = _RELATION_ALIASES.get(r, r)
    return r if r in GRAPH_RELATION_TYPES else "PARTICIPATED_IN"


def _truncate_for_graph_extract(text: str) -> str:
    t = (text or "").strip()
    if len(t) <= GRAPH_EXTRACT_TEXT_MAX:
        return t
    half = GRAPH_EXTRACT_TEXT_MAX // 2
    return t[:half] + "\n\n...[중간 생략: 그래프 추출 길이 제한]...\n\n" + t[-half:]


def _parse_entities_from_raw(entities_raw: Any) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    if not isinstance(entities_raw, list):
        return entities
    for row in entities_raw:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        try:
            imp = int(row.get("importance", 3) or 3)
        except (TypeError, ValueError):
            imp = 3
        entities.append(
            {
                "name": name,
                "type": _normalize_type(row.get("type"), "CHAR"),
                "status": str(row.get("status", "unknown")).strip().lower() or "unknown",
                "origin_hint": str(row.get("origin_hint", "")).strip(),
                "importance": max(1, min(5, imp)),
            }
        )
    return entities


def _parse_relations_from_raw(rels_raw: Any) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    if not isinstance(rels_raw, list):
        return relations
    for row in rels_raw:
        if not isinstance(row, dict):
            continue
        sub = str(row.get("subject", "")).strip()
        obj = str(row.get("object", "")).strip()
        if not sub or not obj:
            continue
        try:
            conf = float(row.get("confidence", 0.7) or 0.7)
        except (TypeError, ValueError):
            conf = 0.7
        relations.append(
            {
                "subject": sub,
                "subject_type": _normalize_type(row.get("subject_type"), "CHAR"),
                "relation": _normalize_relation(row.get("relation")),
                "object": obj,
                "object_type": _normalize_type(row.get("object_type"), "CHAR"),
                "context": str(row.get("context", "")).strip(),
                "confidence": max(0.0, min(1.0, conf)),
            }
        )
    return relations


def _dedupe_relations(rels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for r in rels:
        key = (r["subject"], r["object"], r["relation"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _entity_name_set(entities: list[dict[str, Any]]) -> set[str]:
    return {str(e.get("name", "")).strip() for e in entities if str(e.get("name", "")).strip()}


def _snap_relation_endpoints(
    relations: list[dict[str, Any]], valid_names: set[str]
) -> list[dict[str, Any]]:
    """Neo4j MERGE와 맞추기 위해 subject/object가 엔티티 name 집합에 없는 행은 제거."""
    if not valid_names:
        return []
    out: list[dict[str, Any]] = []
    for r in relations:
        sub = str(r.get("subject", "")).strip().strip("'\"""")
        obj = str(r.get("object", "")).strip().strip("'\"""")
        if sub not in valid_names or obj not in valid_names or sub == obj:
            continue
        row = dict(r)
        row["subject"] = sub
        row["object"] = obj
        out.append(row)
    return out


def _heuristic_relations(body: str, entities: list[dict[str, Any]], *, max_rels: int = 40) -> list[dict[str, Any]]:
    """LLM이 관계를 비운 경우: 본문에서 이름 쌍이 가까이 나오면 INVOLVED_IN 보강."""
    names: list[tuple[str, str]] = []
    for e in entities:
        n = str(e.get("name", "")).strip()
        if len(n) < 2:
            continue
        names.append((n, _normalize_type(e.get("type"), "CHAR")))
    if len(names) < 2:
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    window = 200
    for i, (n1, t1) in enumerate(names):
        for n2, t2 in names[i + 1 :]:
            p1, p2 = body.find(n1), body.find(n2)
            if p1 < 0 or p2 < 0:
                continue
            if abs(p1 - p2) > window:
                continue
            a, b = (n1, t1), (n2, t2)
            if n1 > n2:
                a, b = (n2, t2), (n1, t1)
            key = (a[0], b[0])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "subject": a[0],
                    "subject_type": a[1],
                    "relation": "PARTICIPATED_IN",
                    "object": b[0],
                    "object_type": b[1],
                    "context": "본문 근접 등장(자동 보강)",
                    "confidence": 0.32,
                }
            )
            if len(out) >= max_rels:
                return out
    return out


async def extract_graph_facts(text: str) -> dict[str, list[dict[str, Any]]]:
    body = _truncate_for_graph_extract(text)
    raw = await llm.complete_chat_bible(
        relation_extract_system(),
        relation_extract_user(body),
        temperature=0.15,
    )
    parsed = _extract_json_object(raw)
    entities = _parse_entities_from_raw(parsed.get("entities", []))
    relations = _parse_relations_from_raw(parsed.get("relations", []))
    valid = _entity_name_set(entities)
    relations = _snap_relation_endpoints(relations, valid)
    relations = _dedupe_relations(relations)

    if len(entities) >= 2 and len(body) > 120 and len(relations) < 2:
        raw2 = await llm.complete_chat_bible(
            relation_extract_pass2_system(),
            relation_extract_pass2_user(entities, body),
            temperature=0.12,
        )
        p2 = _extract_json_object(raw2)
        rel2 = _parse_relations_from_raw(p2.get("relations", []))
        rel2 = _snap_relation_endpoints(rel2, valid)
        if rel2:
            relations = _dedupe_relations(relations + rel2)
            logger.info("graph extract: pass2 added %s relations", len(rel2))

    if len(entities) >= 2 and len(relations) < 2:
        hr = _heuristic_relations(body, entities)
        hr = _snap_relation_endpoints(hr, valid)
        if hr:
            relations = _dedupe_relations(relations + hr)
            logger.info("graph extract: heuristic added %s relations", len(hr))

    return {"entities": entities, "relations": relations}


def _neo4j_http_url_sanity(url: str) -> None:
    u = (url or "").strip().lower()
    if "neo4j://" in u or "bolt://" in u or ":7687" in u:
        raise RuntimeError(
            "NEO4J_HTTP_URL 이 Bolt(neo4j:// / bolt:// / :7687)로 보입니다. "
            "이 앱은 HTTP 트랜잭션 API만 사용합니다. 예: http://127.0.0.1:7474"
        )


def _neo4j_error_messages(errors: list[dict[str, Any]]) -> str:
    return "; ".join(str(e.get("message", "unknown")) for e in errors if isinstance(e, dict))


def _neo4j_response_json(r: httpx.Response) -> dict[str, Any]:
    try:
        body = r.json()
    except json.JSONDecodeError as e:
        raise Neo4jHttpError(
            f"Neo4j HTTP 응답이 JSON이 아닙니다: {r.text[:300]!r}",
            status_code=r.status_code,
        ) from e
    return body if isinstance(body, dict) else {}


def _neo4j_errors_from_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    errors = body.get("errors") or []
    return [e for e in errors if isinstance(e, dict)] if isinstance(errors, list) else []


def _is_database_unavailable_error(exc: BaseException | str) -> bool:
    msg = str(exc)
    return "DatabaseUnavailable" in msg or "Requested database is not available" in msg


def _parse_query_api_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        return []
    fields = data.get("fields") or []
    values = data.get("values") or []
    if not isinstance(fields, list) or not isinstance(values, list):
        return []
    rows: list[dict[str, Any]] = []
    for vals in values:
        if isinstance(vals, list):
            rows.append({str(k): v for k, v in zip(fields, vals)})
    return rows


def _parse_tx_commit_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    results = body.get("results") or []
    if not results:
        return rows
    first = results[0] if isinstance(results[0], dict) else {}
    cols = first.get("columns") or []
    for data in first.get("data") or []:
        vals = data.get("row") if isinstance(data, dict) else None
        if isinstance(vals, list):
            rows.append({str(k): v for k, v in zip(cols, vals)})
    return rows


async def _neo4j_post_json(endpoint: str, payload: dict[str, Any], s: Any) -> httpx.Response:
    timeout = httpx.Timeout(connect=20.0, read=120.0, write=120.0, pool=20.0)
    last_net: Exception | None = None
    r: httpx.Response | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(
                    endpoint,
                    auth=(s.neo4j_username, s.neo4j_password),
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
            last_net = None
            break
        except (
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ConnectTimeout,
            OSError,
        ) as e:
            last_net = e
            logger.warning("Neo4j HTTP 요청 실패 (%s/3): %s", attempt, e)
            if attempt < 3:
                await asyncio.sleep(0.45 * attempt)
    if last_net is not None:
        raise RuntimeError(
            f"Neo4j HTTP 연결 실패(재시도 후): {last_net}. "
            "NEO4J_HTTP_URL=http://127.0.0.1:7474 처럼 HTTP 포트인지 확인하세요. "
            "Bolt(7687)에는 HTTP로 붙을 수 없습니다."
        ) from last_net
    assert r is not None
    return r


def _raise_neo4j_http_error(r: httpx.Response, *, database: str, api: str) -> None:
    body = _neo4j_response_json(r)
    errors = _neo4j_errors_from_body(body)
    msg = _neo4j_error_messages(errors) or r.text[:500]
    if _is_database_unavailable_error(msg):
        raise Neo4jHttpError(
            f"Neo4j database '{database}' 사용 불가({api}): {msg}",
            status_code=r.status_code,
            errors=errors,
        )
    raise Neo4jHttpError(
        f"Neo4j HTTP 오류 {r.status_code}({api}, database={database}): {msg}",
        status_code=r.status_code,
        errors=errors,
    )


async def _neo4j_cypher_on_database(
    s: Any,
    base: str,
    database: str,
    query: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    database = (database or "neo4j").strip() or "neo4j"

    query_endpoint = f"{base}/db/{database}/query/v2"
    query_payload = {"statement": query, "parameters": params or {}}
    r = await _neo4j_post_json(query_endpoint, query_payload, s)
    if r.status_code < 400:
        body = _neo4j_response_json(r)
        errs = _neo4j_errors_from_body(body)
        if errs:
            raise Neo4jHttpError(f"Neo4j 쿼리 실패: {_neo4j_error_messages(errs)}", status_code=r.status_code, errors=errs)
        return _parse_query_api_rows(body)

    try:
        query_body = _neo4j_response_json(r)
    except Neo4jHttpError:
        if r.status_code == 404:
            query_body = {}
        else:
            raise
    query_errors = _neo4j_errors_from_body(query_body)
    query_msg = _neo4j_error_messages(query_errors) or r.text[:500]
    if r.status_code != 404 or _is_database_unavailable_error(query_msg):
        _raise_neo4j_http_error(r, database=database, api="query/v2")

    # Neo4j 구버전/설정에서 Query API가 없는 경우만 deprecated transaction HTTP API로 폴백.
    tx_endpoint = f"{base}/db/{database}/tx/commit"
    tx_payload = {"statements": [{"statement": query, "parameters": params or {}}]}
    r = await _neo4j_post_json(tx_endpoint, tx_payload, s)
    if r.status_code >= 400:
        _raise_neo4j_http_error(r, database=database, api="tx/commit")
    body = _neo4j_response_json(r)
    errs = body.get("errors") or []
    if errs:
        msg = "; ".join(e.get("message", "unknown") for e in errs if isinstance(e, dict))
        raise Neo4jHttpError(f"Neo4j 쿼리 실패: {msg}", status_code=r.status_code, errors=errs)
    return _parse_tx_commit_rows(body)


async def _neo4j_default_database(s: Any, base: str) -> str | None:
    queries = [
        "SHOW DEFAULT DATABASE YIELD name, currentStatus RETURN name, currentStatus",
        "SHOW DATABASES YIELD name, currentStatus, default RETURN name, currentStatus, default",
    ]
    for q in queries:
        try:
            rows = await _neo4j_cypher_on_database(s, base, "system", q, {})
        except Exception as e:
            logger.warning("Neo4j 기본 DB 조회 실패: %s", e)
            continue
        for row in rows:
            status = str(row.get("currentStatus") or "").lower()
            is_default = bool(row.get("default", True))
            name = str(row.get("name") or "").strip()
            if name and status in ("online", "") and is_default:
                return name
        for row in rows:
            status = str(row.get("currentStatus") or "").lower()
            name = str(row.get("name") or "").strip()
            if name and status in ("online", "") and name != "system":
                return name
    return None


async def _neo4j_cypher(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    s = get_settings()
    if not s.graph_enabled:
        return []
    if not (s.neo4j_password or "").strip():
        raise RuntimeError("GRAPH_ENABLED=true 인데 NEO4J_PASSWORD가 비어 있습니다.")
    base = (s.neo4j_http_url or "").strip().rstrip("/")
    _neo4j_http_url_sanity(base)
    configured_db = (s.neo4j_database or "neo4j").strip() or "neo4j"
    if configured_db.lower() == "auto":
        detected = await _neo4j_default_database(s, base)
        if not detected:
            raise RuntimeError("NEO4J_DATABASE=auto 이지만 Neo4j 기본 database를 찾지 못했습니다.")
        configured_db = detected
    try:
        return await _neo4j_cypher_on_database(s, base, configured_db, query, params)
    except Neo4jHttpError as e:
        if not _is_database_unavailable_error(e):
            raise
        detected = await _neo4j_default_database(s, base)
        if detected and detected != configured_db:
            logger.warning("Neo4j database %r unavailable, default database %r 로 재시도합니다.", configured_db, detected)
            return await _neo4j_cypher_on_database(s, base, detected, query, params)
        raise RuntimeError(
            f"Neo4j database '{configured_db}' 를 사용할 수 없습니다. "
            "Neo4j Browser에서 `SHOW DATABASES;`로 online database 이름을 확인한 뒤 "
            "backend/.env의 NEO4J_DATABASE를 그 이름으로 바꾸거나 `NEO4J_DATABASE=auto`로 설정하세요. "
            f"원본 오류: {e}"
        ) from e


async def sync_entities_to_graph(
    story_id: uuid.UUID,
    entities: list[dict[str, Any]],
    *,
    origin_kind: str,
    origin_id: str,
) -> int:
    if not entities:
        return 0
    q = """
    UNWIND $entities AS e
    MERGE (n:Entity {story_id: $story_id, name: e.name, node_type: e.type})
    ON CREATE SET n.created_at = datetime()
    SET n.status = coalesce(e.status, n.status, 'unknown'),
        n.importance = coalesce(e.importance, n.importance, 3),
        n.origin_hint = coalesce(e.origin_hint, n.origin_hint, ''),
        n.last_origin_kind = $origin_kind,
        n.last_origin_id = $origin_id,
        n.updated_at = datetime()
    RETURN count(n) AS cnt
    """
    rows = await _neo4j_cypher(
        q,
        {
            "story_id": str(story_id),
            "entities": entities,
            "origin_kind": origin_kind,
            "origin_id": origin_id,
        },
    )
    return int(rows[0].get("cnt", 0)) if rows else 0


async def sync_relations_to_graph(
    story_id: uuid.UUID,
    relations: list[dict[str, Any]],
    *,
    origin_kind: str,
    origin_id: str,
) -> int:
    if not relations:
        return 0
    q = """
    UNWIND $relations AS r
    MERGE (s:Entity {story_id: $story_id, name: r.subject, node_type: r.subject_type})
    MERGE (o:Entity {story_id: $story_id, name: r.object, node_type: r.object_type})
    MERGE (s)-[rel:RELATES {relation_type: r.relation, story_id: $story_id}]->(o)
    ON CREATE SET rel.created_at = datetime()
    SET rel.context = coalesce(r.context, rel.context, ''),
        rel.confidence = coalesce(r.confidence, rel.confidence, 0.7),
        rel.last_origin_kind = $origin_kind,
        rel.last_origin_id = $origin_id,
        rel.updated_at = datetime()
    RETURN count(rel) AS cnt
    """
    rows = await _neo4j_cypher(
        q,
        {
            "story_id": str(story_id),
            "relations": relations,
            "origin_kind": origin_kind,
            "origin_id": origin_id,
        },
    )
    return int(rows[0].get("cnt", 0)) if rows else 0


async def sync_episode_text_to_graph(
    story_id: uuid.UUID,
    episode_id: uuid.UUID,
    text: str,
) -> dict[str, Any]:
    if not get_settings().graph_enabled:
        return {"enabled": False, "entities": 0, "relations": 0}
    facts = await extract_graph_facts(text)
    ent_n = await sync_entities_to_graph(
        story_id,
        facts["entities"],
        origin_kind="episode",
        origin_id=str(episode_id),
    )
    rel_n = await sync_relations_to_graph(
        story_id,
        facts["relations"],
        origin_kind="episode",
        origin_id=str(episode_id),
    )
    return {"enabled": True, "entities": ent_n, "relations": rel_n}


def _bible_category_to_node_type(category: str) -> str:
    c = (category or "").upper().strip()
    return {"CHAR": "CHAR", "LOC": "LOC", "EVENT": "EVENT", "ITEM": "ITEM"}.get(c, "CHAR")


async def sync_bible_entries_to_graph(story_id: uuid.UUID, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not get_settings().graph_enabled:
        return {"enabled": False, "entities": 0}
    entities: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        entities.append(
            {
                "name": name,
                "type": _bible_category_to_node_type(str(row.get("category", ""))),
                "status": str(meta.get("status", "unknown")).strip().lower() or "unknown",
                "importance": int(meta.get("importance", 3) or 3),
                "origin_hint": str(row.get("description", "")).strip()[:300],
            }
        )
    n = await sync_entities_to_graph(
        story_id,
        entities,
        origin_kind="bible",
        origin_id="bible_apply",
    )
    return {"enabled": True, "entities": n}


async def graph_subgraph(
    story_id: uuid.UUID,
    center: str | None = None,
    depth: int = 2,
    limit: int = 120,
    node_types: list[str] | None = None,
) -> dict[str, Any]:
    """Knowledge Graph 하위 그래프를 3D 시각화용 메타와 함께 반환.

    노드에는 `node_type`, `importance`, `status`, `origin_hint`, `degree`,
    링크에는 `relation`, `context`, `confidence` 를 실어 보낸다.
    """
    d = max(1, min(4, depth))
    lim = max(10, min(400, limit))
    if center and center.strip():
        q = """
        MATCH (c:StoryEntity {story_id: $story_id})
        WHERE c.name = $center OR c.entity_id = $center
        MATCH p=(c)-[:RELATES*1..3]-(n:StoryEntity {story_id: $story_id})
        UNWIND relationships(p) AS rel
        WITH startNode(rel) AS src, endNode(rel) AS dst, rel
        RETURN src.name AS source,
               src.entity_type AS source_type,
               src.importance AS source_importance,
               src.status AS source_status,
               src.description AS source_hint,
               dst.name AS target,
               dst.entity_type AS target_type,
               dst.importance AS target_importance,
               dst.status AS target_status,
               dst.description AS target_hint,
               rel.relation_type AS relation,
               rel.context AS context,
               rel.confidence AS confidence,
               rel.relationship_id AS relationship_id
        LIMIT $lim
        """
        rows = await _neo4j_cypher(q, {"story_id": str(story_id), "center": center.strip(), "lim": lim})
    else:
        q = """
        MATCH (a:StoryEntity {story_id: $story_id})-[r:RELATES {story_id: $story_id}]->(b:StoryEntity {story_id: $story_id})
        RETURN a.name AS source,
               a.entity_type AS source_type,
               a.importance AS source_importance,
               a.status AS source_status,
               a.description AS source_hint,
               b.name AS target,
               b.entity_type AS target_type,
               b.importance AS target_importance,
               b.status AS target_status,
               b.description AS target_hint,
               r.relation_type AS relation,
               r.context AS context,
               r.confidence AS confidence,
               r.relationship_id AS relationship_id
        LIMIT $lim
        """
        rows = await _neo4j_cypher(q, {"story_id": str(story_id), "lim": lim})

    if not rows:
        if center and center.strip():
            q = """
            MATCH (c:Entity {story_id: $story_id, name: $center})
            MATCH p=(c)-[:RELATES*1..3]-(n:Entity {story_id: $story_id})
            UNWIND relationships(p) AS rel
            WITH startNode(rel) AS src, endNode(rel) AS dst, rel
            RETURN src.name AS source,
                   src.node_type AS source_type,
                   src.importance AS source_importance,
                   src.status AS source_status,
                   src.origin_hint AS source_hint,
                   dst.name AS target,
                   dst.node_type AS target_type,
                   dst.importance AS target_importance,
                   dst.status AS target_status,
                   dst.origin_hint AS target_hint,
                   rel.relation_type AS relation,
                   rel.context AS context,
                   rel.confidence AS confidence,
                   null AS relationship_id
            LIMIT $lim
            """
            rows = await _neo4j_cypher(q, {"story_id": str(story_id), "center": center.strip(), "lim": lim})
        else:
            q = """
            MATCH (a:Entity {story_id: $story_id})-[r:RELATES {story_id: $story_id}]->(b:Entity {story_id: $story_id})
            RETURN a.name AS source,
                   a.node_type AS source_type,
                   a.importance AS source_importance,
                   a.status AS source_status,
                   a.origin_hint AS source_hint,
                   b.name AS target,
                   b.node_type AS target_type,
                   b.importance AS target_importance,
                   b.status AS target_status,
                   b.origin_hint AS target_hint,
                   r.relation_type AS relation,
                   r.context AS context,
                   r.confidence AS confidence,
                   null AS relationship_id
            LIMIT $lim
            """
            rows = await _neo4j_cypher(q, {"story_id": str(story_id), "lim": lim})

    summary_q = """
    MATCH (s:StorySummary {story_id: $story_id})-[r:MENTIONS_ENTITY|COVERS_EVENT|SUMMARIZES]->(n)
    WHERE $center = ''
       OR s.node_key = $center
       OR s.level = $center
       OR coalesce(n.name, n.title, n.node_key, '') = $center
    RETURN s.node_key AS source,
           'SUMMARY' AS source_type,
           4 AS source_importance,
           s.level AS source_status,
           s.summary AS source_hint,
           coalesce(n.name, n.title, n.node_key, '') AS target,
           CASE
             WHEN n:StoryEntity THEN coalesce(n.entity_type, 'ENTITY')
             WHEN n:StoryEvent THEN 'EVENT'
             WHEN n:StorySummary THEN 'SUMMARY'
             ELSE 'UNKNOWN'
           END AS target_type,
           coalesce(n.importance, 3) AS target_importance,
           coalesce(n.status, n.level, 'known') AS target_status,
           coalesce(n.description, n.summary, '') AS target_hint,
           type(r) AS relation,
           '' AS context,
           0.74 AS confidence,
           null AS relationship_id
    LIMIT $lim
    """
    summary_rows = await _neo4j_cypher(
        summary_q,
        {"story_id": str(story_id), "center": (center or "").strip(), "lim": max(10, lim // 2)},
    )
    if summary_rows:
        rows = rows + summary_rows

    allowed_types: set[str] | None = None
    if node_types:
        allowed_types = {str(t).strip().upper() for t in node_types if str(t).strip()}
        allowed_types = allowed_types or None

    def _coerce_importance(v: Any) -> int:
        try:
            return max(1, min(5, int(v)))
        except (TypeError, ValueError):
            return 3

    def _coerce_confidence(v: Any) -> float | None:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return None

    def _node(name: str, row: dict[str, Any], side: str) -> dict[str, Any]:
        return {
            "id": name,
            "node_type": str(row.get(f"{side}_type", "") or "").strip().upper() or "UNKNOWN",
            "importance": _coerce_importance(row.get(f"{side}_importance")),
            "status": str(row.get(f"{side}_status", "") or "").strip().lower() or "unknown",
            "origin_hint": str(row.get(f"{side}_hint", "") or "").strip()[:240],
            "degree": 0,
        }

    nodes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []
    for row in rows:
        s = str(row.get("source", "")).strip()
        t = str(row.get("target", "")).strip()
        if not s or not t:
            continue
        s_type = str(row.get("source_type", "") or "").strip().upper() or "UNKNOWN"
        t_type = str(row.get("target_type", "") or "").strip().upper() or "UNKNOWN"
        if allowed_types is not None and (
            s_type not in allowed_types or t_type not in allowed_types
        ):
            continue
        if s not in nodes:
            nodes[s] = _node(s, row, "source")
        if t not in nodes:
            nodes[t] = _node(t, row, "target")
        nodes[s]["degree"] += 1
        nodes[t]["degree"] += 1
        links.append(
            {
                "source": s,
                "target": t,
                "relation": str(row.get("relation", "") or "").strip(),
                "context": str(row.get("context", "") or "").strip()[:600],
                "confidence": _coerce_confidence(row.get("confidence")),
                "relationship_id": str(row.get("relationship_id") or "").strip() or None,
            }
        )
    return {
        "nodes": list(nodes.values()),
        "links": links,
        "depth": d,
        "ontology": graph_ontology(),
        "graph_source": "neo4j" if get_settings().graph_enabled else "disabled",
    }


async def graph_context_text(story_id: uuid.UUID, limit: int = 20) -> str:
    if not get_settings().graph_enabled:
        return ""
    q = """
    MATCH (a:StoryEntity {story_id: $story_id})-[r:RELATES {story_id: $story_id}]->(b:StoryEntity {story_id: $story_id})
    RETURN a.name AS source, r.relation_type AS relation, b.name AS target, r.context AS context, r.confidence AS conf
    ORDER BY coalesce(r.confidence, 0.0) DESC, coalesce(r.updated_at, datetime()) DESC
    LIMIT $lim
    """
    rows = await _neo4j_cypher(q, {"story_id": str(story_id), "lim": max(1, min(50, limit))})
    if not rows:
        q = """
        MATCH (a:Entity {story_id: $story_id})-[r:RELATES {story_id: $story_id}]->(b:Entity {story_id: $story_id})
        RETURN a.name AS source, r.relation_type AS relation, b.name AS target, r.context AS context, r.confidence AS conf
        ORDER BY coalesce(r.confidence, 0.0) DESC, coalesce(r.updated_at, datetime()) DESC
        LIMIT $lim
        """
        rows = await _neo4j_cypher(q, {"story_id": str(story_id), "lim": max(1, min(50, limit))})
    if not rows:
        return ""
    raw_lines = [
        f"- {row.get('source', '')} -[{row.get('relation', '')}]-> {row.get('target', '')} ({row.get('context', '')})"
        for row in rows
    ]
    try:
        txt = await llm.complete_chat(
            graph_to_text_system(limit=min(12, limit)),
            graph_to_text_user("\n".join(raw_lines)),
            temperature=0.2,
        )
        return txt.strip()[:2500]
    except Exception as e:
        logger.warning("Graph-to-Text 변환 실패, raw 관계를 사용: %s", e)
        return "\n".join(raw_lines[:12])


async def graph_counts(story_id: uuid.UUID) -> dict[str, int]:
    if not get_settings().graph_enabled:
        return {"nodes": 0, "edges": 0}
    q_nodes = """
    MATCH (n)
    WHERE n.story_id = $story_id AND (n:StoryEntity OR n:StoryEvent OR n:StorySummary OR n:Entity)
    RETURN count(n) AS nodes
    """
    q_edges = """
    MATCH ()-[r]->()
    WHERE r.story_id = $story_id
    RETURN count(r) AS edges
    """
    n_rows = await _neo4j_cypher(q_nodes, {"story_id": str(story_id)})
    e_rows = await _neo4j_cypher(q_edges, {"story_id": str(story_id)})
    return {
        "nodes": int(n_rows[0].get("nodes", 0)) if n_rows else 0,
        "edges": int(e_rows[0].get("edges", 0)) if e_rows else 0,
    }


async def project_episode_memory_to_graph(
    session: AsyncSession,
    story_id: uuid.UUID,
    episode_id: uuid.UUID | None = None,
    *,
    limit: int = 400,
) -> dict[str, Any]:
    """Postgres canonical memory 를 Neo4j 투영으로 복제한다.

    Postgres가 원본이고 Neo4j는 탐색/시각화용 projection 이므로 모든 노드/엣지에는
    Postgres id(entity_id/event_id/relationship_id)를 보존한다.
    """
    if not get_settings().graph_enabled:
        return {"enabled": False, "entities": 0, "events": 0, "relations": 0, "summaries": 0}

    entity_rows = list(
        (
            await session.execute(
                select(StoryEntity)
                .where(StoryEntity.story_id == story_id)
                .order_by(StoryEntity.importance.desc(), StoryEntity.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    event_stmt = select(StoryEvent).where(StoryEvent.story_id == story_id)
    if episode_id is not None:
        event_stmt = event_stmt.where(StoryEvent.source_episode_id == episode_id)
    event_rows = list(
        (
            await session.execute(
                event_stmt.order_by(StoryEvent.chapter_num, StoryEvent.event_order).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    rel_rows = list(
        (
            await session.execute(
                select(StoryRelationship)
                .where(StoryRelationship.story_id == story_id)
                .order_by(StoryRelationship.confidence.desc(), StoryRelationship.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    summary_rows = list(
        (
            await session.execute(
                select(StorySummaryNode)
                .where(StorySummaryNode.story_id == story_id)
                .where(StorySummaryNode.stale == False)  # noqa: E712
                .order_by(StorySummaryNode.depth.asc(), StorySummaryNode.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    entities = [
        {
            "id": str(row.id),
            "name": row.name,
            "entity_type": row.entity_type,
            "status": row.status,
            "importance": row.importance,
            "description": (row.description or "")[:600],
        }
        for row in entity_rows
    ]
    events = [
        {
            "id": str(row.id),
            "title": row.title,
            "summary": (row.summary or "")[:800],
            "chapter_num": row.chapter_num,
            "event_order": row.event_order,
            "importance": row.importance,
        }
        for row in event_rows
    ]
    relationships = [
        {
            "id": str(row.id),
            "source_entity_id": str(row.source_entity_id),
            "target_entity_id": str(row.target_entity_id),
            "relation_type": row.relation_type,
            "current_state": row.current_state or "",
            "confidence": row.confidence,
        }
        for row in rel_rows
    ]
    summaries = [
        {
            "id": str(row.id),
            "node_key": row.node_key,
            "level": row.level,
            "summary": (row.summary or "")[:1000],
            "chapter_start": row.chapter_start,
            "chapter_end": row.chapter_end,
            "parent_id": str(row.parent_id) if row.parent_id else None,
            "entity_ids": row.entity_ids or [],
            "event_ids": row.event_ids or [],
        }
        for row in summary_rows
    ]

    await _neo4j_cypher(
        "MERGE (:Story {story_id: $story_id}) RETURN 1 AS ok",
        {"story_id": str(story_id)},
    )
    if episode_id:
        await _neo4j_cypher(
            """
            MERGE (episode:Episode {story_id: $story_id, episode_id: $episode_id})
            SET episode.updated_at = datetime()
            RETURN 1 AS ok
            """,
            {"story_id": str(story_id), "episode_id": str(episode_id)},
        )
    if entities:
        await _neo4j_cypher(
            """
            MATCH (story:Story {story_id: $story_id})
            UNWIND $entities AS e
            MERGE (n:StoryEntity {story_id: $story_id, entity_id: e.id})
            ON CREATE SET n.created_at = datetime()
            SET n.name = e.name,
                n.entity_type = e.entity_type,
                n.status = e.status,
                n.importance = e.importance,
                n.description = e.description,
                n.updated_at = datetime()
            MERGE (story)-[:HAS_ENTITY]->(n)
            RETURN count(n) AS cnt
            """,
            {"story_id": str(story_id), "entities": entities},
        )
    if events:
        await _neo4j_cypher(
            """
            MATCH (story:Story {story_id: $story_id})
            UNWIND $events AS ev
            MERGE (event:StoryEvent {story_id: $story_id, event_id: ev.id})
            ON CREATE SET event.created_at = datetime()
            SET event.title = ev.title,
                event.summary = ev.summary,
                event.chapter_num = ev.chapter_num,
                event.event_order = ev.event_order,
                event.importance = ev.importance,
                event.updated_at = datetime()
            MERGE (story)-[:HAS_EVENT]->(event)
            RETURN count(event) AS cnt
            """,
            {"story_id": str(story_id), "events": events},
        )
    if episode_id and events:
        await _neo4j_cypher(
            """
            MATCH (episode:Episode {story_id: $story_id, episode_id: $episode_id})
            UNWIND $events AS ev
            MATCH (event:StoryEvent {story_id: $story_id, event_id: ev.id})
            MERGE (episode)-[:HAS_EVENT]->(event)
            RETURN count(event) AS cnt
            """,
            {"story_id": str(story_id), "episode_id": str(episode_id), "events": events},
        )
    if relationships:
        await _neo4j_cypher(
            """
            UNWIND $relationships AS r
            MATCH (s:StoryEntity {story_id: $story_id, entity_id: r.source_entity_id})
            MATCH (t:StoryEntity {story_id: $story_id, entity_id: r.target_entity_id})
            MERGE (s)-[rel:RELATES {story_id: $story_id, relationship_id: r.id}]->(t)
            ON CREATE SET rel.created_at = datetime()
            SET rel.relation_type = r.relation_type,
                rel.current_state = r.current_state,
                rel.context = r.current_state,
                rel.confidence = r.confidence,
                rel.updated_at = datetime()
            RETURN count(rel) AS cnt
            """,
            {"story_id": str(story_id), "relationships": relationships},
        )
    if summaries:
        await _neo4j_cypher(
            """
            MATCH (story:Story {story_id: $story_id})
            UNWIND $summaries AS s
            MERGE (node:StorySummary {story_id: $story_id, summary_node_id: s.id})
            ON CREATE SET node.created_at = datetime()
            SET node.node_key = s.node_key,
                node.level = s.level,
                node.summary = s.summary,
                node.chapter_start = s.chapter_start,
                node.chapter_end = s.chapter_end,
                node.updated_at = datetime()
            MERGE (story)-[:HAS_SUMMARY]->(node)
            RETURN count(node) AS cnt
            """,
            {"story_id": str(story_id), "summaries": summaries},
        )
        await _neo4j_cypher(
            """
            UNWIND $summaries AS s
            WITH s WHERE s.parent_id IS NOT NULL
            MATCH (parent:StorySummary {story_id: $story_id, summary_node_id: s.parent_id})
            MATCH (child:StorySummary {story_id: $story_id, summary_node_id: s.id})
            MERGE (parent)-[:SUMMARIZES {story_id: $story_id}]->(child)
            RETURN count(child) AS cnt
            """,
            {"story_id": str(story_id), "summaries": summaries},
        )
        await _neo4j_cypher(
            """
            UNWIND $summaries AS s
            MATCH (node:StorySummary {story_id: $story_id, summary_node_id: s.id})
            UNWIND s.entity_ids AS entity_id
            MATCH (entity:StoryEntity {story_id: $story_id, entity_id: entity_id})
            MERGE (node)-[:MENTIONS_ENTITY {story_id: $story_id}]->(entity)
            RETURN count(entity) AS cnt
            """,
            {"story_id": str(story_id), "summaries": summaries},
        )
        await _neo4j_cypher(
            """
            UNWIND $summaries AS s
            MATCH (node:StorySummary {story_id: $story_id, summary_node_id: s.id})
            UNWIND s.event_ids AS event_id
            MATCH (event:StoryEvent {story_id: $story_id, event_id: event_id})
            MERGE (node)-[:COVERS_EVENT {story_id: $story_id}]->(event)
            RETURN count(event) AS cnt
            """,
            {"story_id": str(story_id), "summaries": summaries},
        )
    return {
        "enabled": True,
        "entities": len(entities),
        "events": len(events),
        "relations": len(relationships),
        "summaries": len(summaries),
        "graph_source": "canonical_memory",
    }


def conflict_resolution_harness(
    postgres_status: str | None,
    graph_status: str | None,
    *,
    policy: str,
) -> dict[str, Any]:
    ps = (postgres_status or "unknown").strip().lower()
    gs = (graph_status or "unknown").strip().lower()
    if ps == gs:
        return {"resolved": ps, "conflict": False, "policy": policy}
    if policy == "postgres":
        return {"resolved": ps, "conflict": True, "policy": policy}
    if policy == "graph":
        return {"resolved": gs, "conflict": True, "policy": policy}
    return {
        "resolved": "manual",
        "conflict": True,
        "policy": "manual",
        "detail": f"postgres={ps}, graph={gs}",
    }
