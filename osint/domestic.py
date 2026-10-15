"""국내 기보도 확인: 네이버 뉴스 검색으로 최근 N일 안에 같은 내용 기사가 있는지 센다.

결과는 '자동 검색 기준'이다. 0건이면 '선제 보도 후보'로 표시하되, 최종 판단은 데스크가 한다.
"""

import os
from datetime import datetime, timedelta, timezone

from balje import collect

from . import watchlist as wl

CHANNEL_TERM = {"courts": "미국 소송", "nhtsa": "미국 리콜", "eu_comp": "EU", "china_media": "중국",
                "gov_press": "주정부", "sec": "", "pr_wire": "", "local_media": "", "trade_media": "", "feeds": "",
                "fed_register": "미국", "us_federal": "미국", "china_gov": "중국", "kr_gov": "", "global_media": ""}


def ko_short(entity):
    """국내 기사에서 흔히 쓰는 짧은 이름(현대자동차 → 현대차)."""
    names = sorted((n for n in entity.get("ko", []) if n), key=len)
    return names[0] if names else entity["name"]


def heuristic_queries(cand, watch):
    """기업 짧은 이름 + 지역 + 채널 성격(리콜·소송 등)으로 한 개의 좁은 검색어를 만든다.
    SEC 공시는 상대 회사 영문명을 붙인다(국내 기사에도 영문으로 자주 나온다)."""
    e = wl.entity(watch, cand.entity) or {"name": cand.entity, "ko": [cand.entity]}
    parts = [ko_short(e)]
    if cand.location:
        loc = wl.location(watch, cand.location)
        if loc:
            parts.append(loc.get("ko") or loc["name"].split()[0])
    lead = cand.signals[0]
    term = CHANNEL_TERM.get(lead.channel, "")
    if lead.channel == "sec" and lead.meta.get("company"):
        term = lead.meta["company"].split(",")[0].split("(")[0].split()[0]
    for w in term.split():
        if w not in parts:
            parts.append(w)
    return [" ".join(parts)]


def check(queries, config, days=30, now=None, fetch=None):
    """검색어별 최근 days일 기사 수와 예시. 네이버 키가 없으면 None."""
    if not (config.get("naver_client_id") or os.environ.get("NAVER_CLIENT_ID")):
        return None
    fetch = fetch or collect.fetch_naver
    now = now or datetime.now(timezone.utc)
    cut = now - timedelta(days=days)
    total, examples, used = 0, [], []
    for q in queries:
        try:
            arts = fetch(q, 1, client_id=config.get("naver_client_id"),
                         client_secret=config.get("naver_client_secret"))
        except Exception:  # noqa: BLE001 - 검색 실패는 '미확인'으로
            continue
        used.append(q)
        words = q.split()
        recent = [a for a in arts if (a.published is None or a.published >= cut)
                  and all(w.lower() in f"{a.title} {a.description}".lower() for w in words)]
        total += len(recent)
        examples += [(a.press, a.published, a.title, a.link) for a in recent[:2]]
    if not used:
        return None
    return {"count": total, "queries": used, "examples": examples[:4], "days": days}
