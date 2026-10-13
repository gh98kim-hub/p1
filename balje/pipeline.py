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
    md_path = out / f"발제노트_{stamp}.md"
    html_path = out / f"발제노트_{stamp}.html"
    md_path.write_text(report.to_markdown(clusters, notes, now, ai_text, top, meta), encoding="utf-8")
    html_path.write_text(report.to_html(clusters, notes, now, ai_text, top, meta), encoding="utf-8")
    if save_raw:
        collect.save_articles(articles, out / f"기사원본_{stamp}.json")
    if use_history:
        analyze.save_history(config["history_file"], history, articles, now)

    log("\n상위 이슈")
    for rank, c in enumerate(clusters[:top], 1):
        log(f" {rank:>2}. [{c.score:>5}] {c.headline} ({len(c.articles)}건/{len(c.press)}곳)")
    log(f"\n저장: {md_path}\n      {html_path}")
    return {"md": md_path, "html": html_path, "clusters": clusters, "ai_text": ai_text}
