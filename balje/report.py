"""발제 노트 출력(마크다운·HTML)."""

import html
import re
from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))


def _t(dt, fmt="%m-%d %H:%M"):
    return dt.astimezone(KST).strftime(fmt) if dt else "-"


def to_markdown(clusters, notes, generated_at, ai_text=None, top=10, meta=None):
    meta = meta or {}
    out = [f"# 발제 노트 {_t(generated_at, '%Y-%m-%d %H:%M')}", ""]
    out.append(f"- 수집 기사 {meta.get('articles', 0)}건 → 이슈 {len(clusters)}개로 묶음")
    if meta.get("keywords"):
        out.append("- 검색어: " + ", ".join(meta["keywords"]))
    if meta.get("materials"):
        out.append("- 기자 제공 자료: " + ", ".join(meta["materials"]))
    out += ["", "## 오늘의 이슈 순위", "",
            "| 순위 | 이슈 | 점수 | 기사 | 매체 | 상태 | 분류 |",
            "|---|---|---|---|---|---|---|"]
    for rank, c in enumerate(clusters[:top], 1):
        n = notes[c.id]
        title = c.headline.replace("|", "/")
        out.append(f"| {rank} | {c.id} {title} | {c.score} | {len(c.articles)} | {len(c.press)} | "
                   f"{', '.join(n['status'])} | {', '.join(c.angles) or '-'} |")

    if ai_text:
        out += ["", "---", "", "# AI 발제안 (초안 · 반드시 확인 후 사용)", "", ai_text]

    out += ["", "---", "", "# 이슈별 상세", ""]
    for rank, c in enumerate(clusters[:top], 1):
        n = notes[c.id]
        out.append(f"## {rank}. [{c.id}] {c.headline}")
        out.append("")
        out.append(f"- 점수 {c.score} ({' · '.join(c.reasons)})")
        out.append(f"- 키워드: {', '.join(c.keywords) or '-'}")
        out.append(f"- 첫 보도 {_t(c.first_seen)} / 최근 {_t(c.latest)}")
        out.append(f"- 보도 매체: {', '.join(c.press) or '-'}")
        if c.numbers:
            out.append(f"- 제목 속 수치: {', '.join(c.numbers)}")
        out.append("- 발제 각도:")
        out += [f"  - {a}" for a in n["angles"]]
        out.append("- 취재 체크리스트:")
        out += [f"  - [ ] {x}" for x in n["checks"]]
        out.append("- 근거 기사:")
        for a in c.articles[:10]:
            out.append(f"  - [{a.id}] {a.press} {_t(a.published)} [{a.title}]({a.link})")
        if len(c.articles) > 10:
            out.append(f"  - 외 {len(c.articles) - 10}건")
        out.append("")

    rest = clusters[top:]
    if rest:
        out += ["## 기타 이슈", ""]
        out += [f"- [{c.id}] {c.headline} ({len(c.articles)}건, 점수 {c.score})" for c in rest[:40]]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- HTML

_CSS = """
:root { --bg:#fafaf7; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e0d8; --accent:#1f4e8c; --card:#fff; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151514; --fg:#ecebe6; --muted:#a3a29b; --line:#33322f; --accent:#8fb4ea; --card:#1d1d1b; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.65 "Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  word-break:keep-all; overflow-wrap:anywhere; }
main { max-width:920px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:22px; margin:8px 0 4px; } h2 { font-size:18px; margin:28px 0 8px; }
h3 { font-size:16px; margin:20px 0 6px; }
a { color:var(--accent); }
.meta, .muted { color:var(--muted); font-size:13px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th { white-space:nowrap; }
th, td { border-bottom:1px solid var(--line); padding:6px 4px; text-align:left; vertical-align:top; }
.wrap { overflow-x:auto; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; margin:12px 0; }
.chip { display:inline-block; border:1px solid var(--line); border-radius:10px; padding:0 8px;
  font-size:12px; margin-right:4px; color:var(--muted); }
.ai { background:var(--card); border-left:3px solid var(--accent); padding:4px 16px; }
ul { padding-left:20px; margin:4px 0; }
"""


def _md_inline(text):
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text


def _md_block(md):
    """AI 결과용 간단 마크다운 변환(제목·목록·문단)."""
    out, in_list = [], False
    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_md_inline(s[2:])}</li>")
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


def to_html(clusters, notes, generated_at, ai_text=None, top=10, meta=None):
    meta = meta or {}
    e = html.escape
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>발제 노트 {_t(generated_at, '%m-%d')}</title><style>{_CSS}</style></head><body><main>",
         f"<h1>발제 노트 {_t(generated_at, '%Y-%m-%d %H:%M')}</h1>",
         f"<p class='meta'>수집 기사 {meta.get('articles', 0)}건 → 이슈 {len(clusters)}개"
         + (f" · 검색어 {e(', '.join(meta['keywords']))}" if meta.get("keywords") else "")
         + (f" · 기자 제공 자료 {e(', '.join(meta['materials']))}" if meta.get("materials") else "")
         + "</p>",
         "<h2>오늘의 이슈 순위</h2><div class='wrap'><table>",
         "<tr><th>#</th><th>이슈</th><th>점수</th><th>기사</th><th>매체</th><th>상태</th></tr>"]
    for rank, c in enumerate(clusters[:top], 1):
        n = notes[c.id]
        h.append(f"<tr><td>{rank}</td><td><a href='#{c.id}'>{e(c.headline)}</a>"
                 f"<div class='muted'>{e(', '.join(c.angles))}</div></td><td>{c.score}</td>"
                 f"<td>{len(c.articles)}</td><td>{len(c.press)}</td><td>{e(', '.join(n['status']))}</td></tr>")
    h.append("</table></div>")

    if ai_text:
        h.append("<h2>AI 발제안 <span class='muted'>(초안 · 반드시 확인 후 사용)</span></h2>")
        h.append(f"<div class='ai'>{_md_block(ai_text)}</div>")

    h.append("<h2>이슈별 상세</h2>")
    for rank, c in enumerate(clusters[:top], 1):
        n = notes[c.id]
        h.append(f"<div class='card' id='{c.id}'><h3>{rank}. {e(c.headline)}</h3>")
        h.append("<div>" + "".join(f"<span class='chip'>{e(s)}</span>" for s in n["status"] + c.angles) + "</div>")
        h.append(f"<p class='meta'>점수 {c.score} · {e(' · '.join(c.reasons))}<br>"
                 f"키워드 {e(', '.join(c.keywords) or '-')} · 첫 보도 {_t(c.first_seen)} · 최근 {_t(c.latest)}<br>"
                 f"매체 {e(', '.join(c.press) or '-')}</p>")
        h.append("<b>발제 각도</b><ul>" + "".join(f"<li>{e(a)}</li>" for a in n["angles"]) + "</ul>")
        h.append("<b>취재 체크리스트</b><ul>" + "".join(f"<li>☐ {e(x)}</li>" for x in n["checks"]) + "</ul>")
        h.append("<b>근거 기사</b><ul>")
        for a in c.articles[:10]:
            h.append(f"<li><span class='muted'>[{a.id}] {e(a.press)} {_t(a.published)}</span> "
                     f"<a href='{e(a.link)}' target='_blank' rel='noopener'>{e(a.title)}</a></li>")
        if len(c.articles) > 10:
            h.append(f"<li class='muted'>외 {len(c.articles) - 10}건</li>")
        h.append("</ul></div>")

    rest = clusters[top:]
    if rest:
        h.append("<h2>기타 이슈</h2><ul>")
        h += [f"<li>{e(c.headline)} <span class='muted'>({len(c.articles)}건)</span></li>" for c in rest[:40]]
        h.append("</ul>")
    h.append("</main></body></html>")
    return "\n".join(h)
