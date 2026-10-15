"""엔진1: 발제 레이더. 채널 수집 → 추적 대상 매칭 → 저장(새 신호 판별) → 후보(모자이크·단일)
→ 국내 기보도 확인 → (AI) 발제문 → 리포트·알림."""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from balje import pitch
from balje.llm import PROVIDERS, strip_bold

from . import candidates as cand_mod
from . import domestic, prompts, report
from . import watchlist as wl
from .sources import courts, federal_register, news, nhtsa, sec_edgar
from .store import Store

CHECK_TEMPLATES = {
    "sec": "{company} 공시({form}, {date})에 나온 계약·투자 규모와 시점 — 회사 확인",
    "courts": "'{case}' 사건 — 회사 입장, 예상 영향(배상·생산 차질)",
    "nhtsa": "리콜 {campaign} — 미국 대상 대수, 국내 판매 차량 중 같은 부품 사용 여부",
    "gov_press": "현지 정부 발표({source}, {date})와 본사 투자·고용 계획 일치 여부, 인센티브 조건",
    "pr_wire": "파트너사 발표({source}, {date}) — 국내 발표 계획, 사업 규모",
    "eu_comp": "EU 경쟁총국 건({date}) — 심사 일정, 예상 결론",
    "local_media": "현지 매체({source}) 보도 사실 여부 — 현지 법인 공식 입장",
    "trade_media": "업계지({source}) 보도 내용 — 회사 확인",
    "china_media": "중국 매체({source}) 보도 — 현지 법인·합작사 사실관계",
    "feeds": "{source} 발표 내용 — 회사 확인",
    "fed_register": "연방관보 문서({source}, {date}) — 적용 대상·시행 시점, 국내 기업 영향 범위",
    "us_federal": "미 연방정부 발표({source}, {date}) — 해당 부처 원문과 국내 기업 영향",
    "china_gov": "중국 정부 발표({source}, {date}) — 원문 조항과 현지 법인 영향",
    "kr_gov": "정부 보도자료({source}, {date}) — 담당 부처 확인, 업계 반응",
    "global_media": "외신({source}) 보도 사실 여부 — 회사 공식 입장",
}


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- 수집

def collect(config, watch, store, now=None, log=print, only=None):
    """채널별 수집. (신호 목록, 채널 상태)를 돌려준다."""
    now = now or _now()
    ocfg = config["osint"]
    chs = ocfg["channels"]
    days = ocfg.get("lookback_days", 7)
    since = now - timedelta(days=days)
    status, signals = {}, []

    def run(key, fn):
        ch = chs.get(key, {})
        if not ch.get("enabled") or (only and key not in only):
            return
        t0 = time.time()
        try:
            got = fn(ch) or []
            status[key] = {"name": ch.get("name", key), "count": len(got), "error": "", "sec": round(time.time() - t0, 1)}
            signals.extend(got)
            log(f"[{ch.get('name', key)}] {len(got)}건")
        except Exception as e:  # noqa: BLE001 - 한 채널 실패가 전체를 막지 않게
            status[key] = {"name": ch.get("name", key), "count": 0, "error": str(e)[:200], "sec": round(time.time() - t0, 1)}
            log(f"[{ch.get('name', key)}] 실패: {e}")

    def sec_fn(ch):
        out = []
        for name in wl.search_names(watch, "en", tuple(ch.get("priorities", ["high", "mid"]))):
            try:
                got = sec_edgar.search(f'"{name}"', since, now, ch.get("forms", ""), config.get("sec_email", ""))
            except Exception as e:  # noqa: BLE001
                if "403" in str(e):
                    raise RuntimeError("SEC가 접속을 거부했습니다(403). [설정]에 실제 연락처 이메일을 넣었는지 확인하세요. "
                                       "넣었는데도 막히면 회사망·공용망 차단일 수 있습니다.") from e
                log(f"[SEC] {name} 실패: {e}")
                continue
            for s in got:
                s.meta["query_entity"] = name
            out += got
            time.sleep(0.15)
        return out

    def courts_fn(ch):
        token = config.get("courtlistener_token", "")
        names = wl.search_names(watch, "en", tuple(ch.get("priorities", ["high", "mid"])))
        out = []
        n = ch.get("entities_per_query", 6)
        for i in range(0, len(names), n):
            q = " OR ".join(f'"{x}"' for x in names[i:i + n])
            for kind in ch.get("kinds", ["r", "o"]):
                out += courts.search(q, token, since, kind)
                time.sleep(0.3)
        return out

    def nhtsa_fn(ch):
        last = store.get("nhtsa_last")
        if last and datetime.fromisoformat(last) > now - timedelta(hours=ch.get("refresh_hours", 12)):
            log("[NHTSA] 최근에 확인함 → 이번에는 건너뜀")
            return []
        year = now.year + (1 if now.month >= 7 else 0)   # 하반기엔 다음 연식이 나와 있다
        years = list(range(year, year - ch.get("model_years", 4), -1))
        got = nhtsa.search(list(ch.get("makes", {})), years, now - timedelta(days=max(days, 14)), log=log)
        for s in got:
            make = (s.meta.get("vehicles") or [""])[0].split(" ")[1:2]
            ent = ch.get("makes", {}).get(make[0].upper() if make else "", "")
            if ent:
                s.entities = [ent]
        store.set("nhtsa_last", now.isoformat())
        return got

    def fed_fn(ch):
        names = wl.search_names(watch, "en", tuple(ch.get("priorities", ["high", "mid"])))[: ch.get("max_entities", 30)]
        out, seen = [], set()
        jobs = [(f'"{n}"', False) for n in names] + [(t, True) for t in ch.get("topics", [])]
        for term, topic in jobs:
            try:
                got = federal_register.search(term, since, ch.get("per_page", 20))
            except Exception as e:  # noqa: BLE001 - 검색어 하나 실패가 채널 전체를 막지 않게
                log(f"[연방관보] {term} 실패: {e}")
                if "403" in str(e) or "timed out" in str(e):
                    raise
                continue
            for s in got:
                if s.uid in seen:
                    continue
                seen.add(s.uid)
                if topic:
                    s.meta["keep"] = True        # 정책 주제 검색은 기업명이 없어도 보여준다
                    s.meta["topic"] = term
                out.append(s)
            time.sleep(0.2)
        return out

    def kr_gov_fn(ch):
        got = news.read_feeds(ch.get("feeds", []), "kr_gov", log=log)
        for s in got:
            s.lang = "ko"
        names = [n for e in watch["entities"] for n in e.get("ko", [])]
        terms = ch.get("terms", [])
        out = []
        for s in got:
            if s.published and s.published < since:
                continue
            text = f"{s.title} {s.text}"
            if any(t in text for t in terms) or any(n and n in text for n in names):
                s.meta["keep"] = True
                out.append(s)
        return out

    run("sec", sec_fn)
    run("courts", courts_fn)
    run("nhtsa", nhtsa_fn)
    run("fed_register", fed_fn)
    for key in ("us_federal", "gov_press", "eu_comp", "china_gov", "pr_wire",
                "local_media", "trade_media", "global_media", "china_media"):
        run(key, lambda ch, key=key: news.search_channel(key, ch, watch, days, log=log))
    run("kr_gov", kr_gov_fn)
    run("feeds", lambda ch: news.read_feeds(ch.get("list", []), "feeds", log=log))
    return signals, status


def tag(signals, watch):
    """추적 대상·지역 매칭. 대상이 없는 신호는 버린다(정책 주제·정부 보도자료처럼 keep 표시가 있으면 남김)."""
    out = []
    for s in signals:
        text = f"{s.title} {s.text} {' '.join(s.meta.get('biz_locations', []))}"
        ents = wl.match_entities(text, watch)
        if s.channel == "sec" and s.meta.get("query_entity"):
            # 전문 검색은 본문에서 찾은 것이라 제목엔 없을 수 있다
            q = s.meta["query_entity"]
            ents += [e["name"] for e in watch["entities"] if q in e["en"]]
        s.entities = list(dict.fromkeys(s.entities + ents))
        s.locations = wl.match_locations(text, watch)
        if s.entities or s.meta.get("keep"):
            out.append(s)
    return out


# ---------------------------------------------------------------- 후보·자료

def materials_text(cands, max_text=1500):
    lines = []
    for c in cands:
        d = c.domestic
        dom = ("미확인(네이버 키 없음 또는 검색 실패)" if d is None else
               f"최근 {d['days']}일 '{' / '.join(d['queries'])}' 검색 {d['count']}건"
               + ("" if not d["examples"] else " · 예: " + "; ".join(f"{p} {t}" for p, _, t, _ in d["examples"][:2])))
        lines.append(f"### 후보 {c.id} ({'모자이크' if c.kind == 'mosaic' else '단일 신호'} · 대상 {c.entity}"
                     + (f" · 지역 {c.location}" if c.location else "") + f" · 점수 {c.score})")
        lines.append(f"국내 보도(자동 검색): {dom}")
        for i, s in enumerate(c.signals[:6], 1):
            when = s.published.strftime("%Y-%m-%d") if s.published else "날짜 미상"
            lines.append(f"[{c.id}-S{i}] 채널 {s.channel} | {s.source} | {when} | {s.title}"
                         + (f" (번역: {s.meta['ko_title']})" if s.meta.get("ko_title") else ""))
            lines.append(f"    URL: {s.url}")
            body = s.meta.get("doc_text") or s.text
            if body:
                body = " ".join(body.split())
                lines.append(f"    내용: {body[:max_text]}{'…' if len(body) > max_text else ''}")
        lines.append("")
    return "\n".join(lines)


def _ko(s):
    """번역이 있으면 '번역 (원문: …)', 없으면 원문."""
    ko = s.meta.get("ko_title")
    return f"{ko} (원문: {s.title})" if ko else s.title


def _when(x):
    return x.published.strftime("%Y-%m-%d") if x.published else "날짜 미상"


def verdict(c):
    """(짧은 판정, 머리말 태그)."""
    d = c.domestic
    if d is None:
        return "국내 미확인", "[국내 보도 미확인]"
    if d["count"] == 0:
        return "선제 보도 후보", "[선제 보도 후보 · 국내 미보도]"
    return f"후속 · 국내 {d['count']}건", f"[후속 발제 후보 · 국내 {d['count']}건]"


def checklist(c):
    checks = []
    for x in c.signals[:4]:
        tpl = CHECK_TEMPLATES.get(x.channel)
        if tpl:
            checks.append(tpl.format(company=x.meta.get("company", x.source), form=x.meta.get("form", ""),
                                     date=_when(x), case=x.meta.get("case", x.title),
                                     campaign=x.meta.get("campaign", ""), source=x.source))
    checks.append("1차 출처 원문을 직접 열어 수치·날짜·주체 대조")
    return list(dict.fromkeys(checks))


def skeleton(c, watch=None):
    """자동 정리본(AI 발제문이 없을 때도 같은 형식). 근거는 수집 자료만 쓴다."""
    s = c.lead
    d = c.domestic
    _, tag_ = verdict(c)
    dom = "자동 검색 불가(네이버 키 없음)" if d is None else f"최근 {d['days']}일 '{' / '.join(d['queries'])}' {d['count']}건"
    lines = [f"🚨 {tag_} {c.entity}" + (f" · {c.location}" if c.location else "")
             + f" — {s.meta.get('ko_title') or s.title}", ""]
    lines.append("- 출처" + (" (모자이크: 서로 다른 출처 결합)" if c.kind == "mosaic" else ""))
    for i, x in enumerate(c.signals[:6], 1):
        lines.append(f"  {i}차) {x.source} · {_when(x)} · {_ko(x)}")
        lines.append(f"      {x.url}")
    lines.append(f"- 국내 보도: {dom}")
    if d and d["examples"]:
        for press, _, title, link in d["examples"][:2]:
            lines.append(f"  · {press} {title}")
            lines.append(f"      {link}")
    lines.append("- 핵심 팩트(원문 기준)")
    for x in c.signals[:3]:
        summary = x.meta.get("ko_text") or ""
        lines.append(f"  · {x.meta.get('ko_title') or x.title}" + (f" — {summary}" if summary else ""))
    lines += ["", "✅ 체크리스트", *[f"  ☐ {q}" for q in checklist(c)]]
    return "\n".join(lines)


def _weight(config, s):
    return config["osint"]["channels"].get(s.channel, {}).get("weight", 2)


def translate(cands, config, log=print, signals=(), limit=None):
    """외국어 제목·요약을 한국어로(Claude·Gemini 연결이 있을 때). 후보 근거 → 새 신호 → 나머지 순으로
    limit건까지. 반환: 상태 문구."""
    from balje.translate import needs_translation, translate_items
    limit = config["osint"].get("translate_max", 150) if limit is None else limit
    ordered = [s for c in cands for s in c.signals]
    rest = sorted(signals, key=lambda s: (not s.is_new, -_weight(config, s),
                                          -(s.published.timestamp() if s.published else 0)))
    sigs = {}
    for s in ordered + rest:
        if s.uid not in sigs and not s.meta.get("ko_title") and needs_translation(s.title):
            sigs[s.uid] = s
    items = [(uid, s.title, s.text) for uid, s in list(sigs.items())[:limit]]
    if not items:
        return ""
    tr, label = translate_items(items, config, log)
    for uid, v in tr.items():
        if uid in sigs:
            sigs[uid].meta["ko_title"] = v["title"]
            if v.get("summary"):
                sigs[uid].meta["ko_text"] = v["summary"]
    if label:
        more = len(sigs) - len(items)
        return f"번역: {label}로 외국어 자료 {len(tr)}건" + (f"(나머지 {more}건은 원문)" if more > 0 else "")
    return "번역: 안 함(Claude 구독 로그인이나 Claude·Gemini 키가 있어야 외국어 자료를 번역합니다)"


def fetch_primary_docs(cands, config, log=print):
    """발제 후보 근거 자료의 원문 앞부분을 가져온다(SEC 공시, 정부·기업 사이트, 연방관보).
    구글 뉴스 중계 링크는 원문 주소를 알 수 없어 건너뛴다."""
    from balje.collect import Article, fetch_body
    n = 0
    for c in cands:
        for s in c.signals[:4]:
            if s.meta.get("doc_text") or not s.url or "news.google.com" in s.url:
                continue
            try:
                if s.channel == "sec":
                    s.meta["doc_text"] = sec_edgar.document_text(s.url, config.get("sec_email", ""))
                elif s.channel != "nhtsa":
                    s.meta["doc_text"] = fetch_body(Article(title="", link=s.url), 4000)
            except Exception:  # noqa: BLE001 - 원문을 못 가져와도 요약은 남는다
                continue
            n += bool(s.meta.get("doc_text"))
            time.sleep(0.15)
    if n:
        log(f"1차 출처 원문 {n}건 가져옴")
    return n


def ai_reports(cands, config, log=print):
    provider = config["ai"].get("provider", "claude")
    names = ["claude", "gemini"] if provider == "both" else [provider]
    user = prompts.RADAR_USER.format(materials=materials_text(cands))
    system = prompts.RADAR_SYSTEM
    style = pitch.load_style(config["ai"].get("style_file"))
    if style:
        system += "\n\n" + style
    out = {}
    for n in names:
        if n in PROVIDERS:
            label, fn = PROVIDERS[n]
            log(f"{label} 발제문 작성 중...")
            out[label] = strip_bold(fn(system, user, config))
    return out


# ---------------------------------------------------------------- 실행

def run(config, log=print, use_ai=False, out_dir=None, now=None, only=None, notify=True, fetch_docs=True):
    now = now or _now()
    ocfg = config["osint"]
    watch = wl.load(wl.ensure_file(ocfg["watchlist_file"]))
    store = Store(ocfg["db_file"])
    try:
        log(f"추적 대상 {len(watch['entities'])}곳 · 지역 {len(watch.get('locations', []))}곳")
        raw, status = collect(config, watch, store, now, log, only)
        signals = tag(raw, watch)
        store.upsert(signals, now)
        new = [s for s in signals if s.is_new]
        log(f"추적 대상 관련 신호 {len(signals)}건(새 신호 {len(new)}건)")
        history = store.recent(ocfg.get("mosaic_days", 14), now)
    finally:
        store.close()

    chs = ocfg["channels"]
    cands = cand_mod.build(signals, history, watch, chs)
    for c in cands:
        cand_mod.score(c, watch, chs, now)
    cands.sort(key=lambda c: -c.score)
    cands = cands[: ocfg.get("max_candidates", 8) * 2]
    if cands:
        log(f"후보 {len(cands)}건 국내 보도 확인 중...")
    for c in cands:
        c.domestic = domestic.check(domestic.heuristic_queries(c, watch), config, ocfg.get("domestic_days", 30), now)
        cand_mod.score(c, watch, chs, now)
    cands.sort(key=lambda c: -c.score)
    cands = cands[: ocfg.get("max_candidates", 8)]
    for i, c in enumerate(cands, 1):
        c.id = f"C{i}"

    if fetch_docs and ocfg.get("fetch_docs", True) and cands:
        fetch_primary_docs(cands, config, log)

    tr_note = translate(cands, config, log, signals)
    ai = ai_reports(cands, config, log) if (use_ai and cands) else None
    out = Path(out_dir or config.get("output_dir", "output"))
    out.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone(report.KST).strftime("%Y%m%d_%H%M")
    md_path = out / f"OSINT리포트_{stamp}.md"
    skel = {c.id: skeleton(c, watch) for c in cands}
    data = {"now": now, "cands": cands, "skeletons": skel, "ai": ai, "status": status,
            "signals": signals, "new": new, "lookback": ocfg.get("lookback_days", 7),
            "use_ai": bool(use_ai), "translation": tr_note}
    md_path.write_text(report.radar_markdown(data), encoding="utf-8")
    from . import board
    json_path = out / f"OSINT결과_{stamp}.json"
    bd = board.radar_board(data, config)
    bd["files"] = {"md": md_path.name}
    board.save(bd, json_path)
    log(f"후보 {len(cands)}건 · 자료 {len(signals)}건 · 저장: {json_path}")

    if notify and cands and config.get("telegram_bot_token") and config.get("telegram_chat_id"):
        from . import notify as nt
        sent = nt.send_candidates(config, cands, skel, ai)
        log(f"텔레그램 전송 {sent}건")
    return {"md": md_path, "json": json_path, "cands": cands, "status": status, "signals": signals, "ai": ai}
