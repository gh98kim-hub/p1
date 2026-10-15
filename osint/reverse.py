"""엔진2: 역추적·팩트체크. 타사 한국어 기사 → 엔티티·주장 추출(영문·중문 검색어) → 1차 출처 후보 검색
→ 주장별 원문 대조 리포트."""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from balje import collect
from balje.llm import PROVIDERS

from . import prompts, report
from . import watchlist as wl
from .models import Signal
from .sources import courts, news, sec_edgar


def _now():
    return datetime.now(timezone.utc)


def parse_json(text):
    """AI 응답에서 JSON 객체를 꺼낸다(코드 블록·앞뒤 설명이 붙어도)."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def heuristic_extract(article, watch):
    """AI 없이: 추적 대상 목록에서 기사에 나온 기업을 찾아 영문 검색어를 만든다."""
    ents = []
    for name in wl.match_entities(article, watch):
        e = wl.entity(watch, name)
        ents.append({"ko": name, "en": (e["en"] or [""])[0], "zh": (e["zh"] or [""])[0]})
    locs = [loc for loc in watch.get("locations", []) if loc.get("ko") and loc["ko"] in article]
    queries = []
    for e in ents[:4]:
        if not e["en"]:
            continue
        queries.append(f'"{e["en"]}"')
        for loc in locs[:2]:
            queries.append(f'"{e["en"]}" {loc["en"][0]}' if loc["en"] else "")
    return {"entities": ents, "claims": [], "queries_en": [q for q in queries if q][:6], "queries_zh": []}


def search_sources(ext, config, days=120, log=print, now=None):
    now = now or _now()
    since = now - timedelta(days=days)
    out, seen = [], set()

    def add(items):
        for s in items:
            if s.url and s.url not in seen:
                seen.add(s.url)
                out.append(s)

    for q in ext.get("queries_en", [])[:6]:
        try:
            add(Signal(channel="news_en", title=a.title, url=a.link, published=a.published, source=a.press,
                       text=a.description, query=q) for a in collect.fetch_google_news(q + f" when:{days}d")[:8])
        except Exception as e:  # noqa: BLE001
            log(f"[외신 검색] {q} 실패: {e}")
        time.sleep(0.3)
    for q in ext.get("queries_zh", [])[:3]:
        try:
            hl, gl, ceid = news.LANG["zh"]
            add(Signal(channel="news_zh", title=a.title, url=a.link, published=a.published, source=a.press,
                       text=a.description, lang="zh", query=q)
                for a in collect.fetch_google_news(q + f" when:{days}d", hl, gl, ceid)[:6])
        except Exception as e:  # noqa: BLE001
            log(f"[중국 매체 검색] {q} 실패: {e}")
        time.sleep(0.3)
    names = [e.get("en") for e in ext.get("entities", []) if e.get("en")][:4]
    for name in names:
        try:
            add(sec_edgar.search(f'"{name}"', since, now, "8-K,6-K,10-Q,10-K,S-1,425", config.get("sec_email", ""))[:5])
        except Exception as e:  # noqa: BLE001
            log(f"[SEC] {name} 실패: {e}")
        time.sleep(0.15)
    if names and config.get("courtlistener_token"):
        try:
            add(courts.search(" OR ".join(f'"{n}"' for n in names), config["courtlistener_token"], since, "r")[:6])
        except Exception as e:  # noqa: BLE001
            log(f"[법원] 실패: {e}")
    return out


def sources_text(sources, max_text=800):
    lines = []
    for i, s in enumerate(sources, 1):
        when = s.published.strftime("%Y-%m-%d") if s.published else "날짜 미상"
        lines.append(f"[S{i}] {s.channel} | {s.source} | {when} | {s.title}\n    URL: {s.url}")
        if s.text:
            t = " ".join(s.text.split())
            lines.append(f"    내용: {t[:max_text]}")
    return "\n".join(lines)


def run(article_or_url, config, log=print, use_ai=True, out_dir=None, now=None):
    now = now or _now()
    url = article_or_url.strip() if re.match(r"^https?://\S+$", article_or_url.strip()) else ""
    article = article_or_url
    if url:
        log("기사 본문 가져오는 중...")
        article = collect.fetch_body(collect.Article(title="", link=url), 12000)
        if not article:
            raise RuntimeError("기사 본문을 가져오지 못했습니다. 본문을 직접 붙여 넣어 주세요.")
    watch = wl.load(wl.ensure_file(config["osint"]["watchlist_file"]))

    provider = config["ai"].get("provider", "claude")
    names = (["claude", "gemini"] if provider == "both" else [provider]) if use_ai else []
    ext = None
    if names:
        label, fn = PROVIDERS[names[0]]
        log(f"{label}로 주장·검색어 추출 중...")
        ext = parse_json(fn(prompts.REVERSE_EXTRACT_SYSTEM,
                            prompts.REVERSE_EXTRACT_USER.format(article=article[:12000]), config))
    if not ext:
        if names:
            log("AI 추출 실패 → 추적 대상 목록으로 검색어를 만듭니다.")
        ext = heuristic_extract(article, watch)
    log("검색어: " + " / ".join(ext.get("queries_en", []) + ext.get("queries_zh", [])))

    sources = search_sources(ext, config, log=log, now=now)
    log(f"1차 출처 후보 {len(sources)}건")
    ai = {}
    for n in names:
        label, fn = PROVIDERS[n]
        log(f"{label} 역설계 리포트 작성 중...")
        ai[label] = fn(prompts.REVERSE_SYSTEM, prompts.REVERSE_USER.format(
            article=article[:12000], claims=json.dumps(ext.get("claims", []), ensure_ascii=False, indent=1),
            sources=sources_text(sources)), config)

    out = Path(out_dir or config.get("output_dir", "output"))
    out.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone(report.KST).strftime("%Y%m%d_%H%M")
    d = {"now": now, "url": url, "article": article, "sources": sources, "ai": ai, "extract": ext}
    md_path, html_path = out / f"역추적_{stamp}.md", out / f"역추적_{stamp}.html"
    md_path.write_text(report.reverse_markdown(d), encoding="utf-8")
    html_path.write_text(report.reverse_html(d), encoding="utf-8")
    log(f"저장: {md_path}")
    return {"md": md_path, "html": html_path, "sources": sources, "ai": ai, "extract": ext}
