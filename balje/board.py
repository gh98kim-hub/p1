"""결과 화면(대시보드)용 데이터. 화면과 떼어 두어 저장(JSON)·다시 열기·시험이 쉽다.

형식
- groups: 왼쪽 분류 목록. {key, label, parent, cols}
- rows: 가운데 표의 행. {id, groups[], values[], new, url, detail[]}
- detail: 아래 상세 칸의 블록. {"t": title|sub|h|p|kv|bullets|checks|link|note, ...}
  link 블록은 화면에서 [원문 열기]·[복사] 버튼으로 나온다(주소를 글자로 늘어놓지 않는다).
"""

import json
from datetime import timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
VERSION = 1


# ---------------------------------------------------------------- 블록

def title(x):
    return {"t": "title", "x": x}


def sub(x):
    return {"t": "sub", "x": x}


def h(x):
    return {"t": "h", "x": x}


def p(x):
    return {"t": "p", "x": x}


def note(x):
    return {"t": "note", "x": x}


def kv(pairs):
    return {"t": "kv", "x": [[k, str(v)] for k, v in pairs if v not in (None, "", [])]}


def bullets(items):
    return {"t": "bullets", "x": [str(i) for i in items if i]}


def checks(items):
    return {"t": "checks", "x": [str(i) for i in items if i]}


def link(label, url, extra=""):
    """버튼으로 여는 링크. extra: 같은 줄 뒤에 붙는 흐린 글자."""
    return {"t": "link", "x": label, "url": url or "", "extra": extra}


def when(dt, fmt="%Y-%m-%d"):
    return dt.astimezone(KST).strftime(fmt) if dt else "-"


# ---------------------------------------------------------------- 묶음

class Board:
    def __init__(self, kind, title_text, created=None):
        self.data = {"version": VERSION, "kind": kind, "title": title_text,
                     "created": created.isoformat() if created else "", "summary": [],
                     "columns": {}, "groups": [], "rows": [], "files": {}}
        self._keys = set()

    def columns(self, name, cols):
        """cols: [(제목, 너비, 늘어남 여부)]"""
        self.data["columns"][name] = [list(c) for c in cols]

    def group(self, key, label, cols, parent=""):
        if key not in self._keys:
            self._keys.add(key)
            self.data["groups"].append({"key": key, "label": label, "parent": parent, "cols": cols})
        return key

    def row(self, rid, groups, values, detail, url="", new=False, warn=False):
        self.data["rows"].append({"id": rid, "groups": list(dict.fromkeys(groups)), "values": list(values),
                                  "detail": detail, "url": url or "", "new": bool(new), "warn": bool(warn)})

    def summary(self, line):
        if line:
            self.data["summary"].append(line)


def save(data, path):
    if isinstance(data, Board):
        data = data.data
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "rows" not in data or "groups" not in data:
        raise ValueError("결과 화면 파일 형식이 아닙니다.")
    return data


def rows_in(data, key):
    return [r for r in data["rows"] if key in r["groups"]]


# ---------------------------------------------------------------- 국내 발제 노트

def _article_title(a):
    return f"{a.title_ko} (원문: {a.title})" if getattr(a, "title_ko", "") else a.title


def _issue_detail(c, n, materials_note=""):
    d = [title(c.headline),
         sub(f"최근 {when(c.latest, '%m-%d %H:%M')} · 첫 보도 {when(c.first_seen, '%m-%d %H:%M')} · "
             f"점수 {c.score}" + (f" ({' · '.join(c.reasons)})" if c.reasons else "")),
         kv([("상태", ", ".join(n["status"])), ("분류", ", ".join(c.angles)), ("브랜드", ", ".join(c.brands)),
             ("매체", f"{len(c.press)}곳 — {', '.join(c.press)}" if c.press else ""),
             ("제목 속 수치", ", ".join(c.numbers)), ("묶음 기획", ", ".join(n.get("trends", [])))])]
    r = n.get("release")
    if r:
        d += [h("보도자료 점검"), kv([("판단", f"{r['verdict']} ({r['kind']})"),
                                  ("근거", " / ".join(r["reasons"]) or "-")])]
        if r["angles"]:
            d += [note("살릴 앵글"), bullets(r["angles"])]
    d += [h("발제 각도"), bullets(n["angles"])]
    if n["twists"]:
        d += [h("앵글 바꾸기  (★ 기존 기사에 아직 안 보이는 시각)"),
              bullets([("✓ 이미 다룸 · " if t["covered"] else "★ ") + t["view"] for t in n["twists"]])]
    d += [h("취재 체크리스트"), checks(n["checks"])]
    bodies = [a for a in c.articles if a.body]
    if bodies:
        d.append(h(f"수집한 본문 ({len(bodies)}건)"))
        for a in bodies[:2]:
            d += [note(f"{a.press} · {a.title}"), p(a.body[:1500] + ("…" if len(a.body) > 1500 else ""))]
    d.append(h(f"기사 {len(c.articles)}건 (최신순)"))
    for a in c.articles[:15]:
        d.append(link(_article_title(a), a.link, f"{when(a.published, '%m-%d %H:%M')} · {a.press}"))
        if a.naver_link and a.naver_link != a.link:
            d.append(link("  └ 네이버 뉴스에서 보기", a.naver_link))
    if len(c.articles) > 15:
        d.append(note(f"외 {len(c.articles) - 15}건"))
    return d


def notes_board(clusters, notes, generated_at, ai_text=None, top=10, meta=None):
    """국내 발제 노트 → 결과 화면 데이터. clusters는 화면 정렬 순서."""
    from .report import _ai_items, build_sections
    meta = meta or {}
    sec = build_sections(clusters, notes, top)
    b = Board("notes", f"발제 노트 {when(generated_at, '%Y-%m-%d %H:%M')}", generated_at)
    b.columns("issue", [("최근", 92, False), ("이슈", 420, True), ("기사", 48, False), ("매체", 48, False),
                        ("점수", 56, False), ("상태", 170, False)])
    b.columns("doc", [("항목", 520, True), ("건수", 60, False)])

    n_foreign = sum(len(c.articles) for c in sec["foreign"])
    total = meta.get("articles", 0)
    b.summary(f"수집 기사 {total}건(국내 {total - n_foreign} · 외신 {n_foreign}) → 이슈 {len(clusters)}개 · "
              f"발제 후보 {len(sec['candidates'])} · 보도자료 {len(sec['releases'])} · 외신 {len(sec['foreign'])}")
    if meta.get("keywords"):
        b.summary("검색어: " + ", ".join(meta["keywords"]) + (" + 브랜드 전체" if meta.get("brand_search") else ""))
    if meta.get("materials"):
        b.summary("기자 제공 자료: " + ", ".join(meta["materials"]))
    b.summary(meta.get("translation", ""))

    b.group("cand", "★ 발제 후보", "issue")
    b.group("ai", "AI 발제안", "doc")
    b.group("release", "보도자료 점검", "issue")
    b.group("trend", "묶음 기획 소재", "doc")
    b.group("angle", "앵글 바꾸기", "issue")
    b.group("foreign", "외신", "issue")
    b.group("brand", "브랜드별", "issue")
    b.group("all", "전체 이슈", "issue")

    cand_ids = {c.id for c in sec["candidates"]}
    rel_ids = {c.id for c in sec["releases"]}
    angle_ids = {c.id for c in sec["angles"]}
    brands = [r["brand"] for r in (meta.get("brands") or [])][:40]
    for name in brands:
        b.group(f"brand/{name}", name, "issue", parent="brand")
    for c in clusters:
        n = notes[c.id]
        groups = ["all"]
        if c.id in cand_ids:
            groups.append("cand")
        if c.id in rel_ids:
            groups.append("release")
        if c.id in angle_ids:
            groups.append("angle")
        if c.foreign:
            groups.append("foreign")
        groups += [f"brand/{x}" for x in c.brands if x in brands]
        if any(x in brands for x in c.brands):
            groups.append("brand")
        head = c.headline
        ko = getattr(c.rep or c.articles[0], "title_ko", "")
        if c.foreign and ko:
            head = f"{ko}  ({head})"
        b.row(c.id, groups, [when(c.latest, "%m-%d %H:%M"), head, len(c.articles), len(c.press), c.score,
                             ", ".join(n["status"])], _issue_detail(c, n), url=c.articles[0].link, new=c.is_new)

    items = _ai_items(ai_text)
    if not items:
        b.row("ai-none", ["ai"], ["AI 발제안을 켜지 않았습니다", ""],
              [title("AI 발제안 없음"), p("첫 화면에서 AI를 고르고 다시 만들면 발제안·보도자료 점검·틀어보기 초안이 붙습니다.")])
    for label, text in items:
        b.row(f"ai-{label}", ["ai"], [f"{label} 발제안 (초안 · 반드시 확인 후 사용)", ""],
              [title(f"{label} 발제안"), note("초안이다. 근거 자료 번호를 원문과 대조한 뒤 쓴다."), p(text)])

    for i, t in enumerate(meta.get("trends") or [], 1):
        d = [title(f"{t['category']} — {', '.join(t['brands'])}"),
             note("서로 다른 브랜드에서 같은 유형의 이슈가 나왔다. 묶으면 업계 흐름 기사가 될 수 있다."),
             h("묶을 이슈")]
        for c in t["clusters"]:
            a = c.articles[0]
            d.append(link(c.headline, a.link, f"{a.press} {when(c.latest, '%m-%d %H:%M')} · 기사 {len(c.articles)}건"))
        b.row(f"trend-{i}", ["trend"], [f"{t['category']} — {', '.join(t['brands'])}", len(t["clusters"])], d)
    return b.data


# ---------------------------------------------------------------- 상세 번역([AI 번역] 버튼)

_TEXT_BLOCKS = ("title", "sub", "p", "note", "h", "link")


def detail_texts(detail):
    """상세 블록에서 번역할 글을 {자리: 글}로 뽑는다. kv는 값만(항목 이름은 한국어)."""
    out = {}
    for i, b in enumerate(detail):
        t, x = b.get("t"), b.get("x")
        if b.get("keep"):            # 원문 대조용 블록
            continue
        if t in _TEXT_BLOCKS and isinstance(x, str) and x:
            out[f"{i}"] = x
        elif t in ("bullets", "checks"):
            for j, s in enumerate(x or []):
                out[f"{i}.{j}"] = s
        elif t == "kv":
            for j, (_, v) in enumerate(x or []):
                out[f"{i}.{j}"] = v
    return out


def apply_texts(detail, tr):
    """detail_texts의 자리에 번역을 넣은 새 블록 목록(원본은 그대로)."""
    new = json.loads(json.dumps(detail, ensure_ascii=False))
    for key, text in tr.items():
        i, _, j = key.partition(".")
        if not i.isdigit() or int(i) >= len(new):
            continue
        b = new[int(i)]
        if not j:
            if b.get("t") in _TEXT_BLOCKS:
                b["x"] = text
        elif j.isdigit():
            items = b.get("x") or []
            if int(j) < len(items):
                if b.get("t") == "kv":
                    items[int(j)][1] = text
                else:
                    items[int(j)] = text
    return new
