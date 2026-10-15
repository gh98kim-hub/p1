"""추적 대상 목록(watchlist.json) 읽기·검증·매칭."""

import json
import shutil
import sys
from pathlib import Path

from balje.analyze import _contains

DEFAULT_FILE = Path(__file__).resolve().parent / "default_watchlist.json"
PRIORITY_RANK = {"high": 3, "mid": 2, "low": 1}


class WatchlistError(Exception):
    pass


def _default_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "osint" / "default_watchlist.json"
    return p if p.exists() else DEFAULT_FILE


def ensure_file(path):
    """작업 폴더에 watchlist.json이 없으면 기본 목록을 복사해 둔다(기자가 고쳐 쓰는 파일)."""
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_default_path(), p)
    return p


def load(path=None):
    p = Path(path) if path else _default_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise WatchlistError(f"{p.name} {e.lineno}번째 줄 {e.colno}번째 칸 근처 형식 오류: {e.msg}") from e
    ents = data.get("entities")
    if not isinstance(ents, list) or not ents:
        raise WatchlistError(f"{p.name}에 entities 목록이 없습니다.")
    for i, e in enumerate(ents, 1):
        if not e.get("name"):
            raise WatchlistError(f"{p.name} entities {i}번째 항목에 name이 없습니다.")
        e.setdefault("priority", "mid")
        if e["priority"] not in PRIORITY_RANK:
            raise WatchlistError(f"{e['name']}: priority는 high/mid/low 중 하나여야 합니다.")
        for k in ("ko", "en", "zh", "exclude"):
            e.setdefault(k, [])
        if e["name"] not in e["ko"]:
            e["ko"].insert(0, e["name"])
    for loc in data.setdefault("locations", []):
        loc.setdefault("en", [])
        loc.setdefault("zh", [])
        loc.setdefault("ko", loc.get("name", ""))
    return data


def _strip_excludes(text, entity):
    for x in entity.get("exclude", []):
        text = text.replace(x, " ")
    return text


def match_entities(text, watchlist):
    hits = []
    for e in watchlist["entities"]:
        t = _strip_excludes(text, e)
        if any(_contains(t, a) for a in e["ko"] + e["en"] + e["zh"] if a):
            hits.append(e["name"])
    return hits


def match_locations(text, watchlist):
    return [loc["name"] for loc in watchlist.get("locations", [])
            if any(_contains(text, a) for a in loc["en"] + loc["zh"] if a)]


def entity(watchlist, name):
    return next((e for e in watchlist["entities"] if e["name"] == name), None)


def location(watchlist, name):
    return next((loc for loc in watchlist.get("locations", []) if loc["name"] == name), None)


def top_priority(names, watchlist):
    ranks = [PRIORITY_RANK[entity(watchlist, n)["priority"]] for n in names if entity(watchlist, n)]
    return max(ranks, default=0)


def search_names(watchlist, lang="en", priorities=("high", "mid"), per_entity=1):
    """검색어용 대표 표기. 영문은 첫 표기(가장 정식 이름)만 쓴다."""
    out = []
    for e in watchlist["entities"]:
        if e["priority"] in priorities:
            out += [a for a in e.get(lang, [])[:per_entity] if a]
    return list(dict.fromkeys(out))
