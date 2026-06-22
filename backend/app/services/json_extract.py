import json
import re


def parse_llm_json_array(raw: str) -> list[dict]:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    start = s.find("[")
    end = s.rfind("]")
    if start >= 0 and end > start:
        s = s[start : end + 1]
    data = json.loads(s)
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
    return out


def parse_llm_json_object(raw: str) -> dict:
    """최상위 JSON 객체 { ... } 만 추출. 설문+세그 등 단일 dict 응답용."""
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON 객체를 찾을 수 없습니다")
    s = s[start : end + 1]
    data = json.loads(s)
    if not isinstance(data, dict):
        raise ValueError("최상위가 객체가 아닙니다")
    return data
