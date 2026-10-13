"""수집 → 묶기 → 메모 → (AI) → 출력. 명령줄과 GUI가 함께 쓴다."""

import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from . import analyze, collect, pitch, report
from .config import search_queries


class BaljeError(Exception):
    """사용자에게 그대로 보여줄 오류."""


def run(config, inputs=(), materials_dir=None, hours=None, use_ai=False, top=10,
        out_dir=None, use_history=True, save_raw=False, log=print):
    hours = config["lookback_hours"] if hours is None else hours
    now = datetime.now(timezone.utc)

    # 1) 수집
    articles = []
    if inputs:
        for path in inputs:
            articles += collect.load_articles(path, config.get("press_map"))
        log(f"파일에서 기사 {len(articles)}건 읽음")
    else:
        queries = search_queries(config)
        log(f"네이버 검색어 {len(queries)}개 수집 시작")
        for kw in queries:
            try:
                got = collect.fetch_naver(
                    kw, config["pages_per_keyword"],
                    client_id=config.get("naver_client_id"),
                    client_secret=config.get("naver_client_secret"),
                    press_map=config.get("press_map"),
                )
            except RuntimeError as e:
                raise BaljeError(str(e)) from e
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise BaljeError("네이버 API 키가 올바르지 않거나 검색 API 사용 신청이 안 돼 있습니다.") from e
                log(f"[{kw}] 수집 실패: HTTP {e.code}")
                continue
            except OSError as e:
                log(f"[{kw}] 수집 실패: {e}")
                continue
            log(f"[{kw}] {len(got)}건")
            articles += got
            time.sleep(0.1)  # 네이버 API 초당 호출 제한 대비
        foreign = config.get("foreign", {})
        if foreign.get("enabled") and foreign.get("queries"):
            log(f"외신 검색어 {len(foreign['queries'])}개 수집 시작")
            got_total = 0
            for q in foreign["queries"]:
                try:
                    got = collect.fetch_google_news(q, foreign.get("hl", "en-US"), foreign.get("gl", "US"),
                                                    foreign.get("ceid", "US:en"))
                except (OSError, ValueError, SyntaxError) as e:  # SyntaxError: XML 파싱 실패
                    log(f"[외신 {q}] 수집 실패: {e}")
                    continue
                got_total += len(got)
                articles += got
            log(f"외신 {got_total}건")
        brand_queries = [b["query"] for b in config.get("brands", [])]
        before = len(articles)
        articles = analyze.filter_auto(articles, brand_queries, config.get("auto_terms", []))
        if before != len(articles):
            log(f"자동차와 무관한 브랜드 검색 결과 {before - len(articles)}건 제외")
    materials = collect.load_materials(materials_dir)
    if materials:
        log(f"기자 제공 자료 {len(materials)}개 읽음")

    # 2) 정리·묶기
    articles = analyze.filter_recent(analyze.dedupe(articles), hours, now)
    if not articles:
        raise BaljeError("분석할 기사가 없습니다. 검색어나 시간 범위를 확인하세요.")
    history = analyze.load_history(config["history_file"], config["history_days"], now) if use_history else {}
    clusters = analyze.enrich(analyze.cluster_articles(articles), config, history, now)
    for i, c in enumerate(clusters, 1):
        c.id = f"I{i:02d}"
    n = 0
    for c in clusters:
        for a in c.articles:
            n += 1
            a.id = f"A{n:03d}"
    trends = analyze.cross_trends(clusters)
    notes = {c.id: pitch.rule_based_notes(c, config, trends) for c in clusters}
    brands = analyze.brand_summary(clusters)
    log(f"기사 {len(articles)}건 → 이슈 {len(clusters)}개")

    # 발제 후보(보도자료성·외신 제외 상위 이슈) 기사 본문 수집
    body_cfg = config.get("bodies", {})
    if body_cfg.get("enabled") and not inputs:
        fetch_bodies(clusters, body_cfg, log)

    # 3) AI 발제안(선택)
    ai_text = None
    if use_ai:
        provider = {"claude": "Claude", "gemini": "Gemini", "both": "Claude·Gemini"}.get(
            config["ai"].get("provider"), config["ai"].get("provider"))
        log(f"{provider} 발제안 작성 중... (1~3분 걸릴 수 있음)")
        ai_text = pitch.ai_pitches(clusters, materials, notes, config, trends)

    # 4) 출력
    out = Path(out_dir or config["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone(report.KST).strftime("%Y%m%d_%H%M")
    meta = {
        "articles": len(articles),
        "keywords": [] if inputs else config["keywords"],
        "brand_search": not inputs and config.get("search_brands", True),
        "materials": [m["name"] for m in materials],
        "trends": trends,
        "brands": brands,
    }
    shown = analyze.sort_clusters(clusters, config.get("sort", "latest"))
    meta["sort"] = config.get("sort", "latest")
    md_path = out / f"발제노트_{stamp}.md"
    html_path = out / f"발제노트_{stamp}.html"
    body_path = out / f"기사본문_{stamp}.md"
    has_body = any(a.body for c in clusters for a in c.articles)
    meta["body_file"] = body_path.name if has_body else None
    md_path.write_text(report.to_markdown(shown, notes, now, ai_text, top, meta), encoding="utf-8")
    html_path.write_text(report.to_html(shown, notes, now, ai_text, top, meta), encoding="utf-8")
    if has_body:
        body_path.write_text(report.bodies_markdown(shown, notes, now), encoding="utf-8")
    if save_raw:
        collect.save_articles(articles, out / f"기사원본_{stamp}.json")
    if use_history:
        analyze.save_history(config["history_file"], history, articles, now)

    log("\n이슈 (" + ("최신순" if meta["sort"] == "latest" else "점수순") + ")")
    for rank, c in enumerate(shown[:top], 1):
        log(f" {rank:>2}. [{c.score:>5}] {c.headline} ({len(c.articles)}건/{len(c.press)}곳)")
    log(f"\n저장: {md_path}\n      {html_path}" + (f"\n      {body_path}" if has_body else ""))
    return {"md": md_path, "html": html_path, "body_md": body_path if has_body else None,
            "clusters": shown, "ai_text": ai_text}


def body_candidates(clusters, issues=10):
    """본문을 모을 발제 후보: 점수순 상위, 보도자료성·외신 제외."""
    picked = [c for c in sorted(clusters, key=lambda c: -c.score) if not c.release_kind and not c.foreign]
    return picked[:issues]


def fetch_bodies(clusters, cfg, log=print, fetch=None):
    fetch = fetch or collect.fetch_body
    targets = []
    for c in body_candidates(clusters, cfg.get("issues", 10)):
        # 네이버 뉴스 링크가 있는 기사 → 최신 기사 순으로
        arts = sorted(c.articles, key=lambda a: (not a.naver_link,), reverse=False)
        targets += arts[: cfg.get("per_issue", 2)]
    if not targets:
        return 0
    log(f"발제 후보 기사 본문 {len(targets)}건 수집 중...")
    ok = 0
    for a in targets:
        a.body = fetch(a, cfg.get("max_chars", 6000))
        ok += bool(a.body)
        time.sleep(0.2)
    log(f"본문 수집 {ok}/{len(targets)}건 성공")
    return ok
