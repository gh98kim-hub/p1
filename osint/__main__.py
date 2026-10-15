"""OSINT 데스크 명령줄.

  python -m osint radar                    # 발제 레이더(규칙 기반 뼈대)
  python -m osint radar --ai claude        # + AI 발제문 (claude / gemini / both)
  python -m osint radar --only sec,courts  # 일부 채널만
  python -m osint reverse 기사.txt          # 역추적(파일 또는 URL)
"""

import argparse
import sys
from pathlib import Path

from balje.config import load_config

from . import radar, reverse
from .watchlist import WatchlistError


def main(argv=None):
    p = argparse.ArgumentParser(prog="osint", description="OSINT 데스크")
    p.add_argument("--config", default="config.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("radar", help="발제 레이더")
    r.add_argument("--ai", choices=["claude", "gemini", "both"])
    r.add_argument("--only", help="채널 키(쉼표 구분): sec,courts,nhtsa,gov_press,pr_wire,eu_comp,"
                                  "local_media,trade_media,china_media,feeds")
    r.add_argument("--days", type=int, help="조회 기간(일)")
    r.add_argument("--out")
    v = sub.add_parser("reverse", help="역추적·팩트체크")
    v.add_argument("target", help="기사 URL 또는 기사 본문 텍스트 파일")
    v.add_argument("--ai", choices=["claude", "gemini", "both"], default=None)
    v.add_argument("--out")
    args = p.parse_args(argv)

    config = load_config(args.config)
    if args.ai:
        config["ai"]["provider"] = args.ai
    try:
        if args.cmd == "radar":
            if args.days:
                config["osint"]["lookback_days"] = args.days
            only = set(args.only.split(",")) if args.only else None
            radar.run(config, use_ai=bool(args.ai), out_dir=args.out, only=only)
        else:
            target = args.target
            if not target.startswith("http") and Path(target).exists():
                target = Path(target).read_text(encoding="utf-8")
            reverse.run(target, config, use_ai=bool(args.ai), out_dir=args.out)
    except (WatchlistError, RuntimeError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
