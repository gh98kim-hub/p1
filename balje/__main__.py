"""발제 도우미 실행 진입점.

예)
  python -m balje                       # 네이버 API로 수집 → 발제 노트
  python -m balje --ai                  # + Claude 발제안 초안
  python -m balje --input 모니터링.json   # 모니터링 프로그램 결과 파일 사용
  python -m balje --materials 자료폴더 --ai
"""

import argparse
import sys

from . import pipeline
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
    try:
        pipeline.run(
            config, inputs=args.input, materials_dir=args.materials, hours=args.hours,
            use_ai=args.ai, top=args.top, out_dir=args.out,
            use_history=not args.no_history, save_raw=args.save_raw,
        )
    except pipeline.BaljeError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
