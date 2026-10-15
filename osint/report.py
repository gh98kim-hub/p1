"""OSINT 리포트(마크다운·HTML)."""

import html
import re
from datetime import timedelta, timezone

from balje.report import _CSS, _md_block, _md_link

KST = timezone(timedelta(hours=9))


def _t(dt, fmt="%m-%d %H:%M"):
    return dt.astimezone(KST).strftime(fmt) if dt else "-"


def split_ai(text):
    """AI 결과를 '### 후보 C번호' 단위로 나눈다."""
    parts = {}
    for m in re.finditer(r"^###\s*후보\s*(C\d+)(.*?)(?=^###\s*후보\s*C\d+|\Z)", text or "", flags=re.M | re.S):
        parts[m.group(1)] = m.group(0).strip()
    return parts


def radar_markdown(d):
    out = [f"# OSINT 데스크 리포트 {_t(d['now'], '%Y-%m-%d %H:%M')}", "",
           f"- 조회 기간 최근 {d['lookback']}일 · 추적 대상 관련 신호 {len(d['signals'])}건(새 신호 {len(d['new'])}건)"
           f" · 발제 후보 {len(d['cands'])}건",
           "- 국내 보도 건수는 네이버 자동 검색 기준이다. '선제 보도 후보'는 확인 취재 뒤 데스크가 판단한다.", ""]
    out += ["## 발제 후보", ""]
    if not d["cands"]:
        out.append("> 이번 수집에서는 후보가 없다.")
    for c in d["cands"]:
        out += [f"### {c.id} · {c.entity}" + (f" · {c.location}" if c.location else "")
                + f" (점수 {c.score}: {' · '.join(c.reasons)})", "", d["skeletons"][c.id], ""]
        out.append("**근거 신호**")
        for s in c.signals[:8]:
            out.append(f"- {_t(s.published)} [{s.channel}] {s.source} · {_md_link(s.title, s.url)}"
                       + (" · 새 신호" if s.is_new else ""))
        out.append("")
    for label, text in (d["ai"] or {}).items():
        out += ["---", "", f"## {label} 발제문 (초안 · 반드시 원문 확인 후 사용)", "", text, ""]
    out += ["---", "", "## 채널 상태", "", "| 채널 | 건수 | 소요(초) | 오류 |", "|---|---|---|---|"]
    for k, st in d["status"].items():
        out.append(f"| {st['name']} | {st['count']} | {st['sec']} | {st['error'] or '-'} |")
    out += ["", "## 새 신호 전체", ""]
    for s in sorted(d["new"], key=lambda s: (s.channel, -(s.published.timestamp() if s.published else 0))):
        out.append(f"- [{s.channel}] {_t(s.published)} {s.source} · {_md_link(s.title, s.url)} "
                   f"— {', '.join(s.entities)}" + (f" / {', '.join(s.locations)}" if s.locations else ""))
    return "\n".join(out) + "\n"


def radar_html(d):
    e = html.escape
    ai_parts = {label: split_ai(text) for label, text in (d["ai"] or {}).items()}
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>OSINT 리포트 {_t(d['now'], '%m-%d')}</title><style>{_CSS}"
         ".sk{white-space:pre-wrap;font-size:14px}</style></head><body><main>",
         f"<h1>OSINT 데스크 리포트 {_t(d['now'], '%Y-%m-%d %H:%M')}</h1>",
         f"<p class='meta'>최근 {d['lookback']}일 · 신호 {len(d['signals'])}건(새 신호 {len(d['new'])}) · "
         f"후보 {len(d['cands'])}건 · 국내 보도 건수는 네이버 자동 검색 기준</p>",
         "<nav><a href='#cands'>발제 후보</a><a href='#status'>채널 상태</a><a href='#new'>새 신호</a></nav>",
         "<h2 id='cands'>발제 후보</h2>"]
    if not d["cands"]:
        h.append("<p class='muted'>이번 수집에서는 후보가 없다.</p>")
    for c in d["cands"]:
        h.append(f"<div class='card' id='{c.id}'><h3>{c.id} · {e(c.entity)}"
                 + (f" · {e(c.location)}" if c.location else "") + "</h3>"
                 f"<p class='meta'>점수 {c.score} · {e(' · '.join(c.reasons))}</p>")
        for label, parts in ai_parts.items():
            if c.id in parts:
                h.append(f"<div class='ai'><h3>{e(label)} 발제문</h3>{_md_block(parts[c.id])}</div>")
        h.append(f"<details {'open' if not ai_parts else ''}><summary>규칙 기반 뼈대</summary>"
                 f"<div class='sk'>{e(d['skeletons'][c.id])}</div></details>")
        h.append("<b>근거 신호</b><ul>")
        for s in c.signals[:8]:
            h.append(f"<li><span class='muted'>{_t(s.published)} [{e(s.channel)}] {e(s.source)}</span> "
                     f"<a href='{e(s.url)}' target='_blank' rel='noopener'>{e(s.title)}</a>"
                     + (" <span class='chip'>새 신호</span>" if s.is_new else "") + "</li>")
        h.append("</ul></div>")
    for label, text in (d["ai"] or {}).items():
        if not split_ai(text):   # 형식이 어긋난 응답은 통째로 보여준다
            h.append(f"<div class='ai'><h2>{e(label)} 발제문</h2>{_md_block(text)}</div>")
    h += ["<h2 id='status'>채널 상태</h2><div class='wrap'><table>",
          "<tr><th>채널</th><th>건수</th><th>초</th><th>오류</th></tr>"]
    for st in d["status"].values():
        h.append(f"<tr><td>{e(st['name'])}</td><td>{st['count']}</td><td>{st['sec']}</td>"
                 f"<td class='muted'>{e(st['error'] or '-')}</td></tr>")
    h += ["</table></div>", "<h2 id='new'>새 신호 전체</h2><ul>"]
    for s in sorted(d["new"], key=lambda s: (s.channel, -(s.published.timestamp() if s.published else 0))):
        h.append(f"<li><span class='muted'>[{e(s.channel)}] {_t(s.published)} {e(s.source)}</span> "
                 f"<a href='{e(s.url)}' target='_blank' rel='noopener'>{e(s.title)}</a> "
                 f"<span class='muted'>— {e(', '.join(s.entities))}</span></li>")
    h.append("</ul></main></body></html>")
    return "\n".join(h)


def reverse_markdown(d):
    out = [f"# 역추적 리포트 {_t(d['now'], '%Y-%m-%d %H:%M')}", ""]
    if d.get("url"):
        out.append(f"- 대상 기사: <{d['url']}>")
    out += ["", "## AI 역설계", ""]
    for label, text in (d.get("ai") or {}).items():
        out += [f"### {label}", "", text, ""]
    if not d.get("ai"):
        out.append("> AI를 켜지 않아 출처 후보 목록만 정리했다.")
    out += ["", "## 1차 출처 후보", ""]
    for i, s in enumerate(d["sources"], 1):
        out.append(f"- [S{i}] {_t(s.published)} [{s.channel}] {s.source} · {_md_link(s.title, s.url)}")
    out += ["", "## 대상 기사 원문(앞부분)", "", (d.get("article") or "")[:3000]]
    return "\n".join(out) + "\n"


def reverse_html(d):
    e = html.escape
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>역추적 리포트</title><style>{_CSS}</style></head><body><main>",
         f"<h1>역추적 리포트 {_t(d['now'], '%Y-%m-%d %H:%M')}</h1>"]
    if d.get("url"):
        h.append(f"<p class='meta'>대상 기사: <a href='{e(d['url'])}' target='_blank' rel='noopener'>{e(d['url'])}</a></p>")
    for label, text in (d.get("ai") or {}).items():
        h.append(f"<div class='ai'><h2>{e(label)}</h2>{_md_block(text)}</div>")
    h.append("<h2>1차 출처 후보</h2><ul>")
    for i, s in enumerate(d["sources"], 1):
        h.append(f"<li><span class='muted'>[S{i}] {_t(s.published)} [{e(s.channel)}] {e(s.source)}</span> "
                 f"<a href='{e(s.url)}' target='_blank' rel='noopener'>{e(s.title)}</a></li>")
    h.append("</ul><details><summary>대상 기사 원문</summary>"
             f"<div class='body'>{e((d.get('article') or '')[:6000])}</div></details></main></body></html>")
    return "\n".join(h)
