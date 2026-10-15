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


# ---------------------------------------------------------------- 결과 화면의 [AI 번역] 버튼

TEXT_SYSTEM = """너는 한국 경제지 외신 번역 담당이다. 결과 화면에 나온 제목·요약·원문 발췌를 한국어로 옮긴다.
- 연합뉴스체로 간결하게. 의역·과장·추측을 더하지 않고, 원문에 없는 내용을 보태지 않는다.
- 수치·단위·날짜·사건번호·리콜 번호·공시 번호·URL은 원문 그대로 둔다.
- 기업·기관·지명은 국내 통용 표기로 쓰고, 생소하면 원문을 괄호로 붙인다.
- 이미 한국어인 부분은 그대로 두고 외국어 부분만 옮긴다. 줄바꿈과 목록 기호는 유지한다.
- JSON만 출력한다."""

TEXT_USER = """아래 JSON 객체의 각 값을 한국어로 옮겨, 같은 키를 가진 JSON 객체로만 답하라.

{items}"""

_URL = re.compile(r"https?://\S+")
# 영어 단어 두 개 이상 연속, 또는 한자(중국어) 세 글자 이상 연속이면 외국어가 섞인 글로 본다
_FOREIGN = re.compile(r"[A-Za-z][A-Za-z'’\-]+(?:[\s,.:;/&()]+[A-Za-z][A-Za-z'’\-]+)+|[\u4e00-\u9fff]{3,}")

NO_AI = "번역할 AI 연결이 없습니다. [설정]에서 Claude 구독 로그인을 하거나 Claude·Gemini 키를 넣으세요."


def has_foreign(text):
    return bool(_FOREIGN.search(_URL.sub(" ", text or "")))


def translate_texts(texts, config, log=print, max_chars=8000):
    """texts: {키: 글}. 외국어가 섞인 글만 옮겨 {키: 번역}을 돌려준다.
    AI 연결이 없거나 첫 응답부터 읽을 수 없으면 RuntimeError(화면에 그대로 보여줄 문구)."""
    todo = {str(k): v for k, v in texts.items() if v and has_foreign(v)}
    if not todo:
        return {}
    name = available_provider(config)
    if not name:
        raise RuntimeError(NO_AI)
    label, fn = PROVIDERS[name]
    cfg = dict(config, ai=dict(config.get("ai", {}), effort="low"))
    chunks, cur, size = [], {}, 0
    for k, v in todo.items():
        if cur and size + len(v) > max_chars:
            chunks.append(cur)
            cur, size = {}, 0
        cur[k] = v
        size += len(v)
    if cur:
        chunks.append(cur)
    out = {}
    for i, part in enumerate(chunks):
        reply = fn(TEXT_SYSTEM, TEXT_USER.format(items=json.dumps(part, ensure_ascii=False, indent=0)), cfg)
        res = parse_json(reply)
        if not isinstance(res, dict):
            if i == 0 and not out:
                raise RuntimeError(f"{label} 번역 실패: " + (reply or "빈 응답").strip().lstrip("> ")[:200])
            log(f"{label} 번역 응답 일부를 읽지 못했습니다. 그 부분은 원문 그대로 둡니다.")
            continue
        for k, v in res.items():
            if str(k) in part and isinstance(v, str) and v.strip():
                out[str(k)] = v.strip()
    log(f"{label}로 {len(out)}개 항목 번역")
    return out
