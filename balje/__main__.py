"""발제 도우미 실행 진입점.

예)
  python -m balje                       # 네이버 API로 수집 → 발제 노트
  python -m balje --ai                  # + Claude 발제안 초안
  python -m balje --input 모니터링.json   # 모니터링 프로그램 결과 파일 사용
  python -m balje --materials 자료폴더 --ai
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import analyze, collect, pitch, report
from .config import load_config


def build_parser():
    p = argparse.ArgumentParser(prog="balje", description="자동차 담당 발제 도우미")
    p.add_argument("--config", default="config.json", help="설정 파일(기본 config.json)")
    p.add_argument("--input", action="append", default=[],
                   help="기사 파일(JSON/CSV). 여러 번 지정 가능. 지정하면 네이버 수집을 건너뜀")
    p.add_argument("--keywords", help="검색어(쉼표 구분). 설정 파일 값을 덮어씀")
    p.add_argument("--hours", type=float, help="최근 N시간 기사만")
    p.add_argument("--materials", help="기자 제공 자료 폴더(.txt/.md)")
    p.add_argument("--ai", action="store_true", help="Claude로 발제안 초안 작성")
    p.add_argument("--top", type=int, default=10, help="상세 표시할 이슈 수")
    p.add_argument("--out", help="출력 폴더(기본: 설정의 output_dir)")
    p.add_argument("--no-history", action="store_true", help="신규/지속 판별용 기록을 쓰지 않음")
    p.add_argument("--save-raw", action="store_true", help="수집 기사 원본을 JSON으로 저장")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.keywords:
        config["keywords"] = [k.strip() for k in args.keywords.split(",") if k.strip()]
    hours = args.hours if args.hours is not None else config["lookback_hours"]
    now = datetime.now(timezone.utc)

    # 1) 수집
    articles = []
    if args.input:
        for path in args.input:
            articles += collect.load_articles(path, config.get("press_map"))
        print(f"파일에서 기사 {len(articles)}건 읽음")
    else:
        for kw in config["keywords"]:
            try:
                got = collect.fetch_naver(kw, config["pages_per_keyword"], press_map=config.get("press_map"))
            except RuntimeError as e:
                print(e, file=sys.stderr)
                return 2
            except OSError as e:
                print(f"[{kw}] 수집 실패: {e}", file=sys.stderr)
                continue
            print(f"[{kw}] {len(got)}건")
            articles += got
    materials = collect.load_materials(args.materials)

    # 2) 정리·묶기
    articles = analyze.filter_recent(analyze.dedupe(articles), hours, now)
    if not articles:
        print("분석할 기사가 없습니다.", file=sys.stderr)
        return 1
    history = {} if args.no_history else analyze.load_history(
        config["history_file"], config["history_days"], now)
    clusters = analyze.cluster_articles(articles)
    clusters = analyze.enrich(clusters, config, history, now)
    for i, c in enumerate(clusters, 1):
        c.id = f"I{i:02d}"
    n = 0
    for c in clusters:
        for a in c.articles:
            n += 1
            a.id = f"A{n:03d}"
    notes = {c.id: pitch.rule_based_notes(c, config) for c in clusters}

    # 3) AI 발제안(선택)
    ai_text = None
    if args.ai:
        print("Claude 발제안 작성 중...")
        ai_text = pitch.ai_pitches(clusters, materials, notes, config)

    # 4) 출력
    out_dir = Path(args.out or config["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone(report.KST).strftime("%Y%m%d_%H%M")
    meta = {
        "articles": len(articles),
        "keywords": [] if args.input else config["keywords"],
        "materials": [m["name"] for m in materials],
    }
    md_path = out_dir / f"발제노트_{stamp}.md"
    html_path = out_dir / f"발제노트_{stamp}.html"
    md_path.write_text(report.to_markdown(clusters, notes, now, ai_text, args.top, meta), encoding="utf-8")
    html_path.write_text(report.to_html(clusters, notes, now, ai_text, args.top, meta), encoding="utf-8")
    if args.save_raw:
        collect.save_articles(articles, out_dir / f"기사원본_{stamp}.json")
    if not args.no_history:
        analyze.save_history(config["history_file"], history, articles, now)

    print(f"\n상위 이슈")
    for rank, c in enumerate(clusters[:args.top], 1):
        print(f" {rank:>2}. [{c.score:>5}] {c.headline} ({len(c.articles)}건/{len(c.press)}곳)")
    print(f"\n저장: {md_path}\n      {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
