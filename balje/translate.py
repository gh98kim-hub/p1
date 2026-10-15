"""외신 제목·요약 한국어 번역. Claude·Gemini 키가 있으면 AI 발제안을 끈 상태에서도 번역한다."""

import json
import re

from .llm import PROVIDERS, available_provider, parse_json

HANGUL = re.compile(r"[가-힣]")

SYSTEM = """너는 한국 경제지 외신 번역 담당이다. 영문·중문 기사 제목과 요약을 한국어로 옮긴다.
- 연합뉴스체로 간결하게. 의역·과장·추측을 더하지 않는다.
- 수치·단위·날짜는 원문 그대로. 기업·기관·지명은 국내 통용 표기로 쓰고, 생소하면 원문을 괄호로 붙인다.
- JSON만 출력한다."""

USER = """아래 항목의 title과 text를 한국어로 옮겨 JSON으로만 답하라.
형식: {{"항목id": {{"title": "번역 제목", "summary": "번역 요약(text가 비었으면 빈 문자열)"}}}}

{items}"""


def needs_translation(text):
    """한글이 없으면 번역 대상. 앞의 [리콜 번호]·[소송 기록] 같은 한국어 말머리는 빼고 본다."""
    body = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", text or "")
    return bool(body) and not HANGUL.search(body)


def translate_items(items, config, log=print, chunk=40):
    """items: [(id, title, text)]. 반환: (번역 dict, 쓴 AI 이름 또는 None)."""
    items = [(i, t, x) for i, t, x in items if needs_translation(t)]
    if not items:
        return {}, None
    name = available_provider(config)
    if not name:
        return {}, None
    label, fn = PROVIDERS[name]
    cfg = dict(config, ai=dict(config.get("ai", {}), effort="low"))
    out = {}
    for k in range(0, len(items), chunk):
        part = items[k:k + chunk]
        payload = json.dumps([{"id": str(i), "title": t, "text": (x or "")[:400]} for i, t, x in part],
                             ensure_ascii=False, indent=0)
        res = parse_json(fn(SYSTEM, USER.format(items=payload), cfg))
        if not isinstance(res, dict):
            log(f"{label} 번역 응답을 읽지 못했습니다. 원문 그대로 둡니다.")
            continue
        for key, v in res.items():
            if isinstance(v, dict) and v.get("title"):
                out[str(key)] = {"title": v["title"].strip(), "summary": (v.get("summary") or "").strip()}
    log(f"{label}로 외신 {len(out)}건 번역")
    return out, label
