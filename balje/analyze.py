"""기사 정리·이슈 묶기·점수화. 외부 형태소 분석기 없이 동작하도록 단순 규칙을 쓴다."""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 제목 앞뒤 말머리
_BRACKET = re.compile(r"^\s*[\[\(【<]([^\]\)】>]{1,12})[\]\)】>]\s*")
_JOSA = ("으로", "에서", "에게", "까지", "부터", "보다", "처럼", "이다", "했다", "한다", "된다",
         "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "로", "만")
_STOP = {
    "기자", "뉴스", "단독", "속보", "종합", "포토", "사진", "영상", "그래픽", "등", "및", "위해",
    "대한", "관련", "올해", "지난", "이번", "오늘", "내일", "어제", "가운데", "통해", "따라",
    "것으로", "밝혔다", "전했다", "나섰다", "있다", "없다", "했다", "한다", "이후", "이상",
    "최근", "업계", "국내", "글로벌", "시장", "기업", "회사",
}
_NUMBER = re.compile(
    r"\d[\d,.]*[조억만천]*(?:\d[\d,.]*[조억만천]+)*(?:%|원|달러|대|배|건|명|개|위)?")


def strip_brackets(title):
    tags = []
    while True:
        m = _BRACKET.match(title)
        if not m:
            break
        tags.append(m.group(1).strip())
        title = title[m.end():]
    return title.strip(), tags


def tokenize(text):
    tokens = []
    for raw in re.findall(r"[가-힣A-Za-z0-9]+", text):
        tok = raw
        if re.fullmatch(r"[가-힣]+", tok) and len(tok) >= 3:
            for josa in _JOSA:
                if tok.endswith(josa) and len(tok) - len(josa) >= 2:
                    tok = tok[: -len(josa)]
                    break
        if len(tok) < 2 or tok in _STOP or tok.isdigit():
            continue
        tokens.append(tok.upper() if tok.isascii() else tok)
    return tokens


def _bigrams(text):
    s = re.sub(r"[^가-힣A-Za-z0-9]", "", text)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def similarity(a, b):
    """제목 기준 유사도(0~1). 토큰 겹침과 글자 바이그램 겹침 중 큰 값."""
    ta, tb = set(a["tokens"]), set(b["tokens"])
    shared = len(ta & tb)
    overlap = shared / min(len(ta), len(tb)) if ta and tb and shared >= 2 else 0.0
    ba, bb = a["bigrams"], b["bigrams"]
    jac = len(ba & bb) / len(ba | bb) if ba and bb else 0.0
    return max(overlap, jac)


@dataclass
class Cluster:
    id: str
    articles: list
    keywords: list = field(default_factory=list)
    press: list = field(default_factory=list)
    exclusive: list = field(default_factory=list)
    numbers: list = field(default_factory=list)
    watch_hits: list = field(default_factory=list)
    brands: list = field(default_factory=list)
    angles: list = field(default_factory=list)
    release_kind: str = ""          # "홍보성" / "사업 발표" / "" (보도자료성 아님)
    release_signals: list = field(default_factory=list)
    first_seen: datetime | None = None
    latest: datetime | None = None
    recent_count: int = 0
    is_new: bool = True
    my_press_covered: bool = False
    score: float = 0.0
    reasons: list = field(default_factory=list)

    @property
    def headline(self):
        """대표 제목: 묶음 안에서 공통 토큰을 가장 많이 가진 기사의 제목(말머리 제외)."""
        return strip_brackets(self.articles[0].title)[0]


def dedupe(articles):
    seen_links, seen_titles, out = set(), set(), []
    for a in articles:
        norm = re.sub(r"[^가-힣A-Za-z0-9]", "", strip_brackets(a.title)[0])
        if (a.link and a.link in seen_links) or norm in seen_titles:
            continue
        seen_links.add(a.link)
        seen_titles.add(norm)
        out.append(a)
    return out


def filter_recent(articles, hours, now=None):
    if not hours:
        return articles
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    return [a for a in articles if a.published is None or a.published >= cutoff]


def cluster_articles(articles, threshold=0.45):
    """시간순으로 훑으며 가장 비슷한 묶음에 넣는다(단일 연결)."""
    feats = []
    for a in sorted(articles, key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc)):
        title, tags = strip_brackets(a.title)
        a.tags = tags
        feats.append({"article": a, "tokens": tokenize(title), "bigrams": _bigrams(title)})

    groups = []
    for f in feats:
        best, best_sim = None, threshold
        for g in groups:
            sim = max(similarity(f, m) for m in g)
            if sim >= best_sim:
                best, best_sim = g, sim
        if best is None:
            groups.append([f])
        else:
            best.append(f)

    clusters = []
    for i, g in enumerate(groups, 1):
        counter = Counter(t for m in g for t in set(m["tokens"]))
        # 묶음 안에서 공통 토큰을 가장 많이 가진 기사를 대표로 앞에
        g.sort(key=lambda m: -sum(counter[t] for t in set(m["tokens"])))
        keywords = [t for t, c in counter.most_common(6) if c >= 2 or len(g) == 1][:5]
        clusters.append(Cluster(id=f"I{i:02d}", articles=[m["article"] for m in g], keywords=keywords))
    return clusters


def _contains(text, term):
    # 영문 대문자 약어(MINI, BYD, KGM 등)는 대소문자를 구분해 오탐을 줄인다
    if term.isascii() and term.isupper():
        return term in text
    return term.lower() in text.lower()


def brand_hits(text, brands):
    return [b["name"] for b in brands if any(_contains(text, a) for a in b.get("aliases", [b["name"]]))]


def filter_auto(articles, brand_queries, auto_terms):
    """브랜드 검색어로 들어온 기사 중 자동차 맥락이 없는 기사(야구단·인물 등)를 뺀다."""
    brand_queries = set(brand_queries)
    out = []
    for a in articles:
        if a.keyword in brand_queries:
            text = f"{a.title} {a.description}"
            if not any(_contains(text, t) for t in auto_terms):
                continue
        out.append(a)
    return out


def detect_release(c, text, config):
    """보도자료성 이슈인지 추정한다. (종류, 근거 목록)을 돌려준다."""
    markers = config.get("release_markers", {})
    promo = [t for t in markers.get("홍보성", []) if _contains(text, t)]
    biz = [t for t in markers.get("사업 발표", []) if _contains(text, t)]
    wire = [a.press for a in c.articles if any(w in (a.press or "") for w in config.get("release_press", []))]
    signals = []
    if wire:
        signals.append("보도자료 배포 매체: " + ", ".join(sorted(set(wire))))
    burst = (len(c.press) >= 3 and c.first_seen and c.latest
             and (c.latest - c.first_seen) <= timedelta(hours=3))
    if burst:
        signals.append(f"{len(c.press)}개 매체가 3시간 안에 비슷한 제목으로 보도")
    if promo:
        signals.append("홍보성 표현: " + ", ".join(promo[:4]))
    if biz:
        signals.append("발표형 표현: " + ", ".join(biz[:4]))
    if c.exclusive:
        return "", []
    if promo:
        return "홍보성", signals
    if wire or (biz and (burst or len(c.press) <= 2)):
        return "사업 발표", signals
    return "", []


def enrich(clusters, config, history=None, now=None):
    now = now or datetime.now(timezone.utc)
    history = history or {}
    my_press = (config.get("my_press") or "").strip()
    recent_cut = now - timedelta(hours=6)

    for c in clusters:
        text = " ".join(f"{a.title} {a.description}" for a in c.articles)
        dates = [a.published for a in c.articles if a.published]
        c.first_seen = min(dates) if dates else None
        c.latest = max(dates) if dates else None
        c.recent_count = sum(1 for d in dates if d >= recent_cut)
        c.press = sorted({a.press for a in c.articles if a.press})
        c.exclusive = [a for a in c.articles if any("단독" in t for t in a.tags) or "단독" in a.title[:6]]
        nums = list(dict.fromkeys(
            n.strip() for a in c.articles for n in _NUMBER.findall(a.title) if re.search(r"[^\d,.]", n)
        ))
        # '3조2천억'처럼 더 긴 표기('3조2천억원')의 앞부분인 것은 뺀다
        c.numbers = [n for n in nums if not any(o != n and o.startswith(n) for o in nums)][:8]
        c.brands = brand_hits(text, config.get("brands", []))
        c.watch_hits = c.brands + [t for t in config.get("watch_terms", []) if _contains(text, t)]
        c.angles = [name for name, spec in config.get("angles", {}).items()
                    if any(_contains(text, t) for t in spec.get("terms", []))]
        c.my_press_covered = bool(my_press) and any(my_press in (a.press or "") for a in c.articles)
        c.release_kind, c.release_signals = detect_release(c, text, config)
        seen = sum(1 for a in c.articles if a.link in history)
        c.is_new = seen < max(1, len(c.articles) / 2)
        score_cluster(c)
    clusters.sort(key=lambda c: -c.score)
    return clusters


def score_cluster(c):
    n, p = len(c.articles), len(c.press)
    parts = [
        (min(n, 15) * 1.0, f"기사 {n}건"),
        (min(p, 10) * 2.0, f"매체 {p}곳"),
        (min(len(c.watch_hits), 3) * 3.0, "관심 대상: " + ", ".join(c.watch_hits[:3]) if c.watch_hits else ""),
        (5.0 if c.exclusive else 0.0, "타사 단독 있음"),
        (min(c.recent_count, 5) * 1.0, f"최근 6시간 {c.recent_count}건" if c.recent_count else ""),
        (2.0 if c.numbers else 0.0, "수치 등장" if c.numbers else ""),
        (3.0 if c.is_new else 0.0, "신규 이슈" if c.is_new else ""),
        (-4.0 if c.release_kind == "홍보성" else 0.0, "홍보성 보도자료 감점" if c.release_kind == "홍보성" else ""),
    ]
    c.score = round(sum(v for v, _ in parts), 1)
    c.reasons = [label for v, label in parts if v and label]


def cross_trends(clusters, min_brands=2):
    """서로 다른 브랜드의 같은 유형 이슈를 묶어 '업계 흐름' 기획 후보를 찾는다."""
    groups = {}
    for c in clusters:
        # 홍보성 보도자료는 브랜드가 달라도 같은 유형(할인·캠페인 등)이라 묶을 만하다.
        # 사업 발표는 내용이 제각각이라 각도 분류(신차·전동화 등)로만 묶는다.
        cats = list(c.angles) + (["보도자료·홍보성"] if c.release_kind == "홍보성" else [])
        for cat in cats:
            groups.setdefault(cat, []).append(c)
    trends = []
    for cat, members in groups.items():
        brands = list(dict.fromkeys(b for c in members for b in c.brands))
        if len(members) >= 2 and len(brands) >= min_brands:
            trends.append({"category": cat, "brands": brands, "clusters": members})
    trends.sort(key=lambda t: (-len(t["brands"]), -len(t["clusters"])))
    return trends


def brand_summary(clusters):
    """브랜드별 기사 수·이슈 수·대표 이슈."""
    table = {}
    for c in clusters:
        for b in c.brands:
            row = table.setdefault(b, {"brand": b, "articles": 0, "issues": 0, "top": c})
            row["articles"] += len(c.articles)
            row["issues"] += 1
    return sorted(table.values(), key=lambda r: -r["articles"])


# ---------------------------------------------------------------- 히스토리

def load_history(path, days=14, now=None):
    p = Path(path)
    if not p.exists():
        return {}
    now = now or datetime.now(timezone.utc)
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    cutoff = now - timedelta(days=days)
    out = {}
    for link, ts in data.items():
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                out[link] = ts
        except ValueError:
            continue
    return out


def save_history(path, history, articles, now=None):
    now = now or datetime.now(timezone.utc)
    for a in articles:
        if a.link and a.link not in history:
            history[a.link] = now.isoformat()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=0)
