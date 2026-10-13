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
    angles: list = field(default_factory=list)
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
    return term.lower() in text.lower()


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
        c.numbers = list(dict.fromkeys(
            n.strip() for a in c.articles for n in _NUMBER.findall(a.title) if re.search(r"[^\d,.]", n)
        ))[:8]
        c.watch_hits = [t for t in config.get("watch_terms", []) if _contains(text, t)]
        c.angles = [name for name, spec in config.get("angles", {}).items()
                    if any(_contains(text, t) for t in spec.get("terms", []))]
        c.my_press_covered = bool(my_press) and any(my_press in (a.press or "") for a in c.articles)
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
    ]
    c.score = round(sum(v for v, _ in parts), 1)
    c.reasons = [label for v, label in parts if v and label]


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
