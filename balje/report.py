"""발제 노트 출력(마크다운·HTML). 두 형식 모두 같은 구성으로 쓴다.

1 발제 후보 · 2 AI 발제안 · 3 보도자료 점검 · 4 묶음 기획 소재 · 5 앵글 바꾸기 · 6 외신
· 7 브랜드별 기사량 · 8 전체 이슈 목록
"""

import html
import re
from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))
SORT_LABEL = {"latest": "최신순(가장 최근 기사 기준)", "score": "점수순"}


def _t(dt, fmt="%m-%d %H:%M"):
    return dt.astimezone(KST).strftime(fmt) if dt else "-"


def _ai_items(ai_text):
    if not ai_text:
        return []
    if isinstance(ai_text, str):
        return [("AI", ai_text)]
    return list(ai_text.items())


def build_sections(clusters, notes, top=10):
    """clusters는 화면 정렬 순서. 발제 후보는 점수 상위 top개를 골라 화면 순서대로 보여준다."""
    domestic = [c for c in clusters if not c.foreign]
    foreign = [c for c in clusters if c.foreign]
    pool = [c for c in domestic if not notes[c.id]["release"]]
    best = {c.id for c in sorted(pool, key=lambda c: -c.score)[:top]}
    candidates = [c for c in pool if c.id in best]
    releases = [c for c in domestic if notes[c.id]["release"]]
    angle_items = [c for c in pool if c.id in best or len(c.press) >= 2]
    return {"domestic": domestic, "foreign": foreign, "candidates": candidates,
            "releases": releases, "angles": angle_items}


def anchors(sec):
    """이슈별로 실제 존재하는 링크 대상(상세가 있으면 상세, 없으면 전체 목록의 행)."""
    out = {}
    for c in sec["domestic"]:
        out[c.id] = f"row-{c.id}"
    for c in sec["releases"]:
        out[c.id] = f"r-{c.id}"
    for c in sec["candidates"]:
        out[c.id] = f"d-{c.id}"
    for c in sec["foreign"]:
        out[c.id] = f"f-{c.id}"
    return out


# ---------------------------------------------------------------- 마크다운

def _md_text(text):
    """마크다운 링크 글자 안의 대괄호를 이스케이프한다([단독] 등)."""
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _md_link(text, url):
    if not url:
        return _md_text(text)
    return f"[{_md_text(text)}](<{url}>)"


def _md_article(a):
    line = f"{_t(a.published)} {a.press} · {_md_link(a.title, a.link)}"
    if a.naver_link and a.naver_link != a.link:
        line += f" · {_md_link('네이버', a.naver_link)}"
    return line


def _md_status(c, notes):
    n = notes[c.id]
    parts = [", ".join(n["status"])]
    if c.angles:
        parts.append("분류 " + ", ".join(c.angles))
    if c.brands:
        parts.append("브랜드 " + ", ".join(c.brands))
    return " · ".join(parts)


def to_markdown(clusters, notes, generated_at, ai_text=None, top=10, meta=None):
    meta = meta or {}
    sec = build_sections(clusters, notes, top)
    n_foreign = sum(len(c.articles) for c in sec["foreign"])
    out = [f"# 발제 노트 {_t(generated_at, '%Y-%m-%d %H:%M')}", ""]
    out.append(f"- 수집 기사 {meta.get('articles', 0)}건(국내 {meta.get('articles', 0) - n_foreign} · "
               f"외신 {n_foreign}) → 이슈 {len(clusters)}개")
    if meta.get("keywords"):
        out.append("- 검색어: " + ", ".join(meta["keywords"]) + (" + 브랜드 전체" if meta.get("brand_search") else ""))
    if meta.get("materials"):
        out.append("- 기자 제공 자료: " + ", ".join(meta["materials"]))
    out.append(f"- 정렬: {SORT_LABEL.get(meta.get('sort', 'latest'), '최신순')}")
    if meta.get("body_file"):
        out.append(f"- 발제 후보 기사 본문: {meta['body_file']}")
    out += ["", "## 목차", "",
            "1. 발제 후보", "2. AI 발제안", "3. 보도자료 점검", "4. 묶음 기획 소재",
            "5. 앵글 바꾸기", "6. 외신", "7. 브랜드별 기사량", "8. 전체 이슈 목록"]

    # 1. 발제 후보
    out += ["", "---", "", f"## 1. 발제 후보 ({len(sec['candidates'])}개)", "",
            "> 보도자료성·외신을 뺀 이슈 중 점수 상위. 정렬은 위 기준을 따른다.", ""]
    for c in sec["candidates"]:
        n = notes[c.id]
        out.append(f"### [{c.id}] {c.headline}")
        out.append("")
        out.append(f"- 최근 {_t(c.latest)} · 첫 보도 {_t(c.first_seen)} · 점수 {c.score} ({' · '.join(c.reasons)})")
        out.append(f"- {_md_status(c, notes)}")
        out.append(f"- 매체 {len(c.press)}곳: {', '.join(c.press) or '-'}")
        if c.numbers:
            out.append(f"- 제목 속 수치: {', '.join(c.numbers)}")
        out.append("- 발제 각도")
        out += [f"  - {a}" for a in n["angles"]]
        out.append("- 앵글 바꾸기")
        out += [f"  - {'✓ 이미 다룸' if t['covered'] else '★ 아직 안 나옴'} · {t['view']}" for t in n["twists"]]
        out.append("- 취재 체크리스트")
        out += [f"  - [ ] {x}" for x in n["checks"]]
        bodies = [a for a in c.articles if a.body]
        if bodies:
            first = bodies[0].body.replace("\n", " ")
            out.append(f"- 본문 수집 {len(bodies)}건 (전문은 본문 파일). 발췌: {first[:200]}{'…' if len(first) > 200 else ''}")
        out.append("- 기사(최신순)")
        out += [f"  - {_md_article(a)}" for a in c.articles[:10]]
        if len(c.articles) > 10:
            out.append(f"  - 외 {len(c.articles) - 10}건")
        out.append("")

    # 2. AI
    out += ["---", "", "## 2. AI 발제안", ""]
    items = _ai_items(ai_text)
    if not items:
        out.append("> AI 발제안을 켜지 않았다.")
    for label, text in items:
        out += [f"### {label} (초안 · 반드시 확인 후 사용)", "", text, ""]

    # 3. 보도자료
    out += ["", "---", "", f"## 3. 보도자료 점검 ({len(sec['releases'])}건)", ""]
    if not sec["releases"]:
        out.append("> 보도자료로 보이는 이슈가 없다.")
    for c in sec["releases"]:
        r = notes[c.id]["release"]
        out.append(f"### [{c.id}] {c.headline}")
        out.append("")
        out.append(f"- 판단: **{r['verdict']}** ({r['kind']})")
        out.append(f"- 근거: {' / '.join(r['reasons']) or '-'}")
        out.append("- 살릴 앵글")
        out += [f"  - {x}" for x in r["angles"]] or ["  - -"]
        out.append(f"- 브랜드: {', '.join(c.brands) or '-'} · 최근 {_t(c.latest)}")
        out.append("- 기사")
        out += [f"  - {_md_article(a)}" for a in c.articles[:5]]
        out.append("")

    # 4. 묶음 기획
    trends = meta.get("trends") or []
    out += ["---", "", f"## 4. 묶음 기획 소재 ({len(trends)}건)", "",
            "> 서로 다른 브랜드에서 같은 유형의 이슈가 나왔다. 묶으면 업계 흐름 기사가 될 수 있다.", ""]
    for t in trends:
        out.append(f"### {t['category']} — {', '.join(t['brands'])}")
        out.append("")
        for c in t["clusters"]:
            a = c.articles[0]
            out.append(f"- [{c.id}] {_md_link(c.headline, a.link)} ({a.press} {_t(c.latest)}, 기사 {len(c.articles)}건)")
        out.append("")

    # 5. 앵글 바꾸기
    out += ["---", "", f"## 5. 앵글 바꾸기 ({len(sec['angles'])}건)", "",
            "> 여러 매체가 다룬 이슈와 발제 후보. ★는 기존 기사에 아직 안 보이는 시각.", ""]
    for c in sec["angles"]:
        tw = notes[c.id]["twists"]
        fresh = [t["view"] for t in tw if not t["covered"]]
        done = [t["view"] for t in tw if t["covered"]]
        out.append(f"### [{c.id}] {c.headline} (매체 {len(c.press)}곳)")
        out.append("")
        out.append("- 이미 다룬 시각: " + (" / ".join(done) or "-"))
        out += [f"- ★ {v}" for v in fresh]
        out.append("")

    # 6. 외신
    out += ["---", "", f"## 6. 외신 ({len(sec['foreign'])}건)", ""]
    if not sec["foreign"]:
        out.append("> 외신 수집을 끄거나 결과가 없다.")
    for c in sec["foreign"]:
        out.append(f"### {c.headline}")
        out.append("")
        if c.brands:
            out.append(f"- 브랜드: {', '.join(c.brands)}")
        out += [f"- {_md_article(a)}" for a in c.articles[:6]]
        out.append("")

    # 7. 브랜드
    brands = meta.get("brands") or []
    out += ["---", "", "## 7. 브랜드별 기사량", "", "| 브랜드 | 기사 | 이슈 | 대표 이슈 |", "|---|---|---|---|"]
    for r in brands[:30]:
        out.append(f"| {r['brand']} | {r['articles']} | {r['issues']} | [{r['top'].id}] {r['top'].headline.replace('|', '/')} |")

    # 8. 전체
    out += ["", "---", "", f"## 8. 전체 이슈 목록 ({len(sec['domestic'])}개)", "",
            "| 최근 | 이슈 | 점수 | 기사 | 매체 | 상태 |", "|---|---|---|---|---|---|"]
    for c in sec["domestic"]:
        title = _md_link(c.headline, c.articles[0].link).replace("|", "/")
        out.append(f"| {_t(c.latest)} | [{c.id}] {title} | {c.score} | {len(c.articles)} | {len(c.press)} | "
                   f"{', '.join(notes[c.id]['status'])} |")
    return "\n".join(out) + "\n"


def bodies_markdown(clusters, notes, generated_at):
    out = [f"# 발제 후보 기사 본문 {_t(generated_at, '%Y-%m-%d %H:%M')}", "",
           "> 발제 참고용으로 모은 원문. 기사에 그대로 옮겨 쓰지 않는다.", ""]
    for c in clusters:
        arts = [a for a in c.articles if a.body]
        if not arts:
            continue
        out += [f"## [{c.id}] {c.headline}", ""]
        for a in arts:
            out.append(f"### {a.press} {_t(a.published)} · {_md_text(a.title)}")
            out.append("")
            out.append(f"- 링크: <{a.link}>" + (f" · 네이버: <{a.naver_link}>" if a.naver_link else ""))
            out.append("")
            out.append(a.body)
            out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- HTML

_CSS = """
:root { --bg:#fafaf7; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e0d8; --accent:#1f4e8c; --card:#fff;
  --new:#1d7a46; --warn:#9a5b00; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151514; --fg:#ecebe6; --muted:#a3a29b; --line:#33322f; --accent:#8fb4ea; --card:#1d1d1b;
    --new:#6fcf97; --warn:#e0a85a; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.65 "Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  word-break:keep-all; overflow-wrap:anywhere; }
main { max-width:920px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:22px; margin:8px 0 4px; } h2 { font-size:18px; margin:28px 0 8px; }
h3 { font-size:16px; margin:20px 0 6px; }
a { color:var(--accent); }
nav { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0; }
nav a { font-size:13px; border:1px solid var(--line); border-radius:12px; padding:2px 10px; text-decoration:none; }
.meta, .muted { color:var(--muted); font-size:13px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th { white-space:nowrap; }
th, td { border-bottom:1px solid var(--line); padding:6px 4px; text-align:left; vertical-align:top; }
.wrap { overflow-x:auto; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; margin:12px 0; }
.chip { display:inline-block; border:1px solid var(--line); border-radius:10px; padding:0 8px;
  font-size:12px; margin-right:4px; color:var(--muted); }
.ai { background:var(--card); border-left:3px solid var(--accent); padding:4px 16px; }
.cols { display:grid; gap:12px; grid-template-columns:1fr; }
@media (min-width:900px) { .cols.two { grid-template-columns:1fr 1fr; } main.wide { max-width:1400px; } }
.fresh { color:var(--new); font-weight:600; } .done { color:var(--muted); }
.verdict { font-weight:700; color:var(--warn); min-width:5.5em; }
td:first-child { min-width:2em; }
ul { padding-left:20px; margin:4px 0; }
.nowrap { white-space:nowrap; }
details { margin:6px 0; } summary { cursor:pointer; color:var(--accent); font-size:14px; }
.body { white-space:pre-wrap; font-size:14px; background:var(--bg); border:1px solid var(--line);
  border-radius:6px; padding:10px 12px; margin-top:6px; }
"""


def _md_inline(text):
    text = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def _md_block(md):
    """AI 결과용 간단 마크다운 변환(제목·목록·문단)."""
    out, in_list = [], False
    for line in md.splitlines():
        s = line.rstrip()
        stripped = s.lstrip()
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_md_inline(stripped[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if s.startswith("### "):
            out.append(f"<h3>{_md_inline(s[4:])}</h3>")
        elif s.startswith("## "):
            out.append(f"<h3>{_md_inline(s[3:])}</h3>")
        elif s.startswith("# "):
            out.append(f"<h2>{_md_inline(s[2:])}</h2>")
        elif s.startswith("> "):
            out.append(f"<p class='muted'>{_md_inline(s[2:])}</p>")
        elif s:
            out.append(f"<p>{_md_inline(s)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _h_article(a):
    e = html.escape
    extra = ""
    if a.naver_link and a.naver_link != a.link:
        extra = f" · <a href='{e(a.naver_link)}' target='_blank' rel='noopener'>네이버</a>"
    return (f"<li><span class='muted'>{_t(a.published)} {e(a.press)}</span> "
            f"<a href='{e(a.link)}' target='_blank' rel='noopener'>{e(a.title)}</a>{extra}</li>")


def to_html(clusters, notes, generated_at, ai_text=None, top=10, meta=None):
    meta = meta or {}
    e = html.escape
    sec = build_sections(clusters, notes, top)
    anc = anchors(sec)
    ai_items = _ai_items(ai_text)
    trends = meta.get("trends") or []
    brands = meta.get("brands") or []
    n_foreign = sum(len(c.articles) for c in sec["foreign"])

    def ilink(c, text=None):
        return f"<a href='#{anc[c.id]}'>{e(text or c.headline)}</a>"

    kw = ""
    if meta.get("keywords"):
        kw = f" · 검색어 {e(', '.join(meta['keywords']))}" + (" + 브랜드 전체" if meta.get("brand_search") else "")
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>발제 노트 {_t(generated_at, '%m-%d')}</title><style>{_CSS}</style></head><body>",
         f"<main class='{'wide' if len(ai_items) > 1 else ''}'>",
         f"<h1>발제 노트 {_t(generated_at, '%Y-%m-%d %H:%M')}</h1>",
         f"<p class='meta'>수집 기사 {meta.get('articles', 0)}건(외신 {n_foreign}) → 이슈 {len(clusters)}개{kw}"
         + (f" · 기자 제공 자료 {e(', '.join(meta['materials']))}" if meta.get("materials") else "")
         + f" · 정렬 {SORT_LABEL.get(meta.get('sort', 'latest'), '')}"
         + (f" · 본문 파일 {e(meta['body_file'])}" if meta.get("body_file") else "") + "</p>"]
    nav = [("s1", f"발제 후보 {len(sec['candidates'])}"), ("s2", "AI 발제안"),
           ("s3", f"보도자료 {len(sec['releases'])}"), ("s4", f"묶음 기획 {len(trends)}"),
           ("s5", "앵글 바꾸기"), ("s6", f"외신 {len(sec['foreign'])}"), ("s7", "브랜드별"), ("s8", "전체 목록")]
    h.append("<nav>" + "".join(f"<a href='#{k}'>{v}</a>" for k, v in nav) + "</nav>")

    # 1. 발제 후보
    h.append(f"<h2 id='s1'>1. 발제 후보</h2><p class='muted'>보도자료성·외신을 뺀 점수 상위 {top}개</p>")
    for c in sec["candidates"]:
        n = notes[c.id]
        h.append(f"<div class='card' id='d-{c.id}'><h3>[{c.id}] {e(c.headline)}</h3>")
        h.append("<div>" + "".join(f"<span class='chip'>{e(x)}</span>"
                                   for x in n["status"] + c.angles + c.brands) + "</div>")
        h.append(f"<p class='meta'>최근 {_t(c.latest)} · 첫 보도 {_t(c.first_seen)} · 점수 {c.score} "
                 f"({e(' · '.join(c.reasons))})<br>매체 {len(c.press)}곳: {e(', '.join(c.press) or '-')}"
                 + (f"<br>제목 속 수치: {e(', '.join(c.numbers))}" if c.numbers else "") + "</p>")
        h.append("<b>발제 각도</b><ul>" + "".join(f"<li>{e(a)}</li>" for a in n["angles"]) + "</ul>")
        h.append("<b>앵글 바꾸기</b><ul>" + "".join(
            f"<li class='{'done' if t['covered'] else 'fresh'}'>"
            f"{'이미 다룸' if t['covered'] else '아직 안 나옴'} · {e(t['view'])}</li>" for t in n["twists"]) + "</ul>")
        h.append("<b>취재 체크리스트</b><ul>" + "".join(f"<li>☐ {e(x)}</li>" for x in n["checks"]) + "</ul>")
        h.append("<b>기사(최신순)</b><ul>" + "".join(_h_article(a) for a in c.articles[:10]) + "</ul>")
        for a in [a for a in c.articles if a.body]:
            h.append(f"<details><summary>본문 · {e(a.press)} {e(a.title)}</summary>"
                     f"<div class='body'>{e(a.body)}</div></details>")
        h.append("</div>")

    # 2. AI
    h.append("<h2 id='s2'>2. AI 발제안 <span class='muted'>(초안 · 반드시 확인 후 사용)</span></h2>")
    if not ai_items:
        h.append("<p class='muted'>AI 발제안을 켜지 않았다.</p>")
    else:
        h.append(f"<div class='cols {'two' if len(ai_items) > 1 else ''}'>")
        for label, text in ai_items:
            h.append(f"<div class='ai'><h2>{e(label)}</h2>{_md_block(text)}</div>")
        h.append("</div>")

    # 3. 보도자료
    h.append("<h2 id='s3'>3. 보도자료 점검</h2>")
    if not sec["releases"]:
        h.append("<p class='muted'>보도자료로 보이는 이슈가 없다.</p>")
    for c in sec["releases"]:
        r = notes[c.id]["release"]
        h.append(f"<div class='card' id='r-{c.id}'><h3>[{c.id}] {e(c.headline)}</h3>"
                 f"<p><span class='verdict'>{e(r['verdict'])}</span> <span class='chip'>{e(r['kind'])}</span>"
                 + "".join(f"<span class='chip'>{e(b)}</span>" for b in c.brands) + "</p>"
                 f"<p class='meta'>{'<br>'.join(e(x) for x in r['reasons']) or '-'}</p>"
                 "<b>살릴 앵글</b><ul>" + ("".join(f"<li>{e(x)}</li>" for x in r["angles"]) or "<li>-</li>") + "</ul>"
                 "<b>기사</b><ul>" + "".join(_h_article(a) for a in c.articles[:5]) + "</ul></div>")

    # 4. 묶음 기획
    h.append("<h2 id='s4'>4. 묶음 기획 소재</h2><p class='muted'>서로 다른 브랜드에서 같은 유형의 이슈가 나왔다. "
             "묶으면 업계 흐름 기사가 될 수 있다.</p>")
    if not trends:
        h.append("<p class='muted'>해당 없음.</p>")
    for t in trends:
        h.append(f"<div class='card'><h3>{e(t['category'])} — {e(', '.join(t['brands']))}</h3><ul>")
        for c in t["clusters"]:
            h.append(f"<li>{ilink(c)} <span class='muted'>{e(c.articles[0].press)} {_t(c.latest)} · "
                     f"기사 {len(c.articles)}건</span></li>")
        h.append("</ul></div>")

    # 5. 앵글 바꾸기
    h.append("<h2 id='s5'>5. 앵글 바꾸기</h2><p class='muted'>여러 매체가 다룬 이슈와 발제 후보. "
             "초록색은 기존 기사에 아직 안 보이는 시각.</p><div class='wrap'><table>"
             "<tr><th>이슈</th><th>이미 다룬 시각</th><th>새 시각</th></tr>")
    for c in sec["angles"]:
        tw = notes[c.id]["twists"]
        h.append(f"<tr><td>{ilink(c)}<div class='muted'>매체 {len(c.press)}곳</div></td>"
                 f"<td class='muted'>{'<br>'.join(e(t['view']) for t in tw if t['covered']) or '-'}</td>"
                 f"<td class='fresh'>{'<br>'.join(e(t['view']) for t in tw if not t['covered']) or '-'}</td></tr>")
    h.append("</table></div>")

    # 6. 외신
    h.append("<h2 id='s6'>6. 외신</h2>")
    if not sec["foreign"]:
        h.append("<p class='muted'>외신 수집을 끄거나 결과가 없다.</p>")
    for c in sec["foreign"]:
        h.append(f"<div class='card' id='f-{c.id}' lang='en'><h3>{e(c.headline)}</h3>"
                 + ("".join(f"<span class='chip'>{e(b)}</span>" for b in c.brands))
                 + "<ul>" + "".join(_h_article(a) for a in c.articles[:6]) + "</ul></div>")

    # 7. 브랜드
    h += ["<h2 id='s7'>7. 브랜드별 기사량</h2><div class='wrap'><table>",
          "<tr><th>브랜드</th><th>기사</th><th>이슈</th><th>대표 이슈</th></tr>"]
    for r in brands[:30]:
        h.append(f"<tr><td>{e(r['brand'])}</td><td>{r['articles']}</td><td>{r['issues']}</td>"
                 f"<td>{ilink(r['top'])}</td></tr>")
    h.append("</table></div>")

    # 8. 전체
    h += [f"<h2 id='s8'>8. 전체 이슈 목록 <span class='muted'>({len(sec['domestic'])}개)</span></h2>",
          "<div class='wrap'><table><tr><th>최근</th><th>이슈</th><th>점수</th><th>기사</th><th>상태</th></tr>"]
    for c in sec["domestic"]:
        a = c.articles[0]
        detail = f" <a class='muted' href='#{anc[c.id]}'>상세</a>" if anc[c.id] != f"row-{c.id}" else ""
        h.append(f"<tr id='row-{c.id}'><td class='nowrap'>{_t(c.latest)}</td>"
                 f"<td><a href='{e(a.link)}' target='_blank' rel='noopener'>{e(c.headline)}</a>{detail}"
                 f"<div class='muted'>{e(', '.join(c.angles + c.brands[:3]))}</div></td>"
                 f"<td>{c.score}</td><td>{len(c.articles)}/{len(c.press)}곳</td>"
                 f"<td>{e(', '.join(notes[c.id]['status']))}</td></tr>")
    h.append("</table></div>")
    h.append("</main></body></html>")
    return "\n".join(h)
