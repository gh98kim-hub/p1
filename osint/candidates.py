"""발제 후보 만들기: 모자이크(같은 기업·같은 지역, 서로 다른 채널 신호) + 단일 고가치 신호."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import watchlist as wl


@dataclass
class Candidate:
    kind: str                 # "mosaic" / "single"
    entity: str
    location: str | None
    signals: list
    score: float = 0.0
    domestic: dict | None = None
    id: str = ""
    reasons: list = field(default_factory=list)

    @property
    def channels(self):
        return list(dict.fromkeys(s.channel for s in self.signals))

    @property
    def lead(self):
        return self.signals[0]


def _weight(channels_cfg, key):
    return channels_cfg.get(key, {}).get("weight", 2)


def build(current, history, watch, channels_cfg):
    """current: 이번에 모은 신호(is_new 표시됨), history: 저장소의 최근 신호."""
    pool = {s.uid: s for s in history}
    pool.update({s.uid: s for s in current})

    def prio(name):
        e = wl.entity(watch, name)
        return wl.PRIORITY_RANK.get(e["priority"], 0) if e else 0

    def order(ss):
        return sorted(ss, key=lambda s: (-_weight(channels_cfg, s.channel),
                                          -(s.published or s.first_seen or datetime.min.replace(tzinfo=timezone.utc)).timestamp()))

    cands = []
    groups = defaultdict(dict)
    for s in pool.values():
        for e in s.entities:
            if prio(e) < 2:
                continue
            for loc in s.locations:
                groups[(e, loc)][s.uid] = s
    in_mosaic = set()
    for (e, loc), ss in groups.items():
        ss = list(ss.values())
        if len({s.channel for s in ss}) >= 2 and any(s.is_new for s in ss):
            cands.append(Candidate("mosaic", e, loc, order(ss)))
            in_mosaic |= {(e, s.uid) for s in ss}

    per_key = defaultdict(int)
    for s in order([s for s in current if s.is_new]):
        best = max(s.entities, key=prio, default=None)
        if not best or prio(best) < 2 or (best, s.uid) in in_mosaic:
            continue
        if prio(best) == 2 and _weight(channels_cfg, s.channel) < 3:
            continue
        key = (best, s.channel)
        if per_key[key] >= 3:          # 같은 기업·같은 채널 단일 후보는 3건까지
            continue
        per_key[key] += 1
        cands.append(Candidate("single", best, s.locations[0] if s.locations else None, [s]))
    return cands


def score(c, watch, channels_cfg, now=None):
    now = now or datetime.now(timezone.utc)
    e = wl.entity(watch, c.entity)
    p = wl.PRIORITY_RANK.get(e["priority"], 0) if e else 0
    ch = sum(max(_weight(channels_cfg, s.channel) for s in c.signals if s.channel == k) for k in c.channels)
    parts = [(ch, f"채널 {len(c.channels)}개(가중치 {ch})"), (p * 2, f"추적 우선순위 {e['priority'] if e else '-'}")]
    if c.kind == "mosaic":
        parts.append((3, "모자이크(서로 다른 출처 결합)"))
    newest = max((s.published or s.first_seen for s in c.signals if (s.published or s.first_seen)), default=None)
    if newest and newest >= now - timedelta(days=2):
        parts.append((2, "최근 48시간 신호"))
    d = c.domestic
    if d is not None:
        if d["count"] == 0:
            parts.append((5, "국내 보도 0건"))
        elif d["count"] <= 2:
            parts.append((2, f"국내 보도 {d['count']}건"))
    c.score = round(sum(v for v, _ in parts), 1)
    c.reasons = [label for v, label in parts if v]
    return c.score
