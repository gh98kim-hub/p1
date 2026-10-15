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


# ---------------------------------------------------------------- 키워드로 고치기(프로그램 안 편집 창)

PRIORITY_LABEL = {"high": "높음", "mid": "보통", "low": "낮음"}
PRIORITY_HELP = {"high": "선제 보도 후보까지 올림", "mid": "후보 가능(정부·공시 등 무게 있는 출처일 때)",
                 "low": "맥락용 — 모자이크·역추적에만 씀"}


def _script(word):
    if any("가" <= ch <= "힣" for ch in word):
        return "ko"
    if any("一" <= ch <= "鿿" or "぀" <= ch <= "ヿ" for ch in word):
        return "zh"
    return "en"


def parse_keywords(text):
    """쉼표·줄바꿈으로 나눈 키워드 목록(중복 제거, 순서 유지)."""
    words = [w.strip() for part in (text or "").replace("，", ",").replace("、", ",").splitlines()
             for w in part.split(",")]
    return list(dict.fromkeys(w for w in words if w))


def split_keywords(words):
    """키워드를 글자로 나눠 {ko, en, zh}로. 한글이 있으면 ko, 한자·가나면 zh, 나머지는 en."""
    out = {"ko": [], "en": [], "zh": []}
    for w in words:
        out[_script(w)].append(w)
    return out


def keywords_of(item):
    """편집 창에 보여줄 키워드 한 덩어리(한국어 → 영문 → 중문 순)."""
    ko = item.get("ko", [])
    ko = [ko] if isinstance(ko, str) else ko
    return list(dict.fromkeys(w for w in ko + item.get("en", []) + item.get("zh", []) if w))


def make_entity(name, keywords, priority="mid", exclude=(), base=None):
    """이름·키워드로 추적 대상 항목을 만든다. base(기존 항목)의 다른 칸(group 등)은 유지한다."""
    e = dict(base or {})
    sp = split_keywords([name] + [w for w in keywords if w != name])
    e.update({"name": name, "priority": priority, "ko": sp["ko"], "en": sp["en"], "zh": sp["zh"],
              "exclude": list(dict.fromkeys(x for x in exclude if x))})
    return e


def make_location(name, ko_short, keywords, base=None):
    loc = dict(base or {})
    sp = split_keywords([w for w in keywords if w])
    loc.update({"name": name, "ko": ko_short or (sp["ko"][0] if sp["ko"] else name),
                "en": sp["en"], "zh": sp["zh"]})
    return loc


def quick_add(data, text, priority="mid"):
    """'현대모비스, Hyundai Mobis, 现代摩比斯' → 첫 키워드가 대표 이름. 같은 이름이 있으면 키워드를 보탠다.
    반환: (항목, 새로 만들었는지)."""
    words = parse_keywords(text)
    if not words:
        raise WatchlistError("추가할 키워드를 넣으세요.")
    name = words[0]
    old = entity(data, name)
    if old:
        merged = make_entity(name, keywords_of(old) + words[1:], old.get("priority", priority),
                             old.get("exclude", []), base=old)
        data["entities"][data["entities"].index(old)] = merged
        return merged, False
    e = make_entity(name, words[1:], priority)
    data["entities"].append(e)
    return e, True


def validate(data):
    """저장 전 점검. 문제가 있으면 WatchlistError."""
    names = [e.get("name", "").strip() for e in data.get("entities", [])]
    if not names:
        raise WatchlistError("추적 대상이 하나도 없습니다.")
    if "" in names:
        raise WatchlistError("이름이 빈 추적 대상이 있습니다.")
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise WatchlistError("이름이 겹칩니다: " + ", ".join(dup))
    locs = [loc.get("name", "").strip() for loc in data.get("locations", [])]
    if "" in locs:
        raise WatchlistError("이름이 빈 지역이 있습니다.")
    dup = sorted({n for n in locs if locs.count(n) > 1})
    if dup:
        raise WatchlistError("지역 이름이 겹칩니다: " + ", ".join(dup))


def save(data, path):
    """watchlist.json으로 저장(설명·그룹 등 다른 칸은 그대로). 임시 파일에 쓴 뒤 바꿔 끼워 중간에 깨지지 않게."""
    validate(data)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def warnings(e):
    """편집 창에 보여줄 주의 문구."""
    out = []
    if not e.get("en"):
        out.append("영문 키워드가 없으면 해외 자료(SEC·법원·연방관보·외신)에서 찾지 못합니다.")
    if not e.get("zh") and e.get("priority") == "high":
        out.append("중문 키워드가 없으면 중국 매체·중국 정부 자료에서 찾지 못합니다.")
    # 영문은 단어 단위로 찾으므로(Kia ≠ Nokia) 두 글자 이하만 주의
    short = [w for w in e.get("en", []) if len(w) <= 2 and not w.isupper()]
    if short:
        out.append("아주 짧은 영문 키워드(" + ", ".join(short) + ")는 엉뚱한 기사에 걸릴 수 있습니다. 약어면 대문자로 쓰세요.")
    return out
