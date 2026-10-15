"""OSINT 리포트(마크다운). 프로그램의 결과 보기 창에서 링크를 눌러 바로 열 수 있게 URL을 줄마다 둔다."""

import re
from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))


def _t(dt, fmt="%m-%d %H:%M"):
    return dt.astimezone(KST).strftime(fmt) if dt else "-"


def split_ai(text):
    """AI 결과를 '### 후보 C번호' 단위로 나눈다."""
    parts = {}
    for m in re.finditer(r"^###\s*후보\s*(C\d+)(.*?)(?=^###\s*후보\s*C\d+|\Z)", text or "", flags=re.M | re.S):
        parts[m.group(1)] = m.group(0).strip()
    return parts


def _signal_line(s):
    title = s.meta.get("ko_title") or s.title
    return [f"- {_t(s.published)} [{s.channel}] {s.source} · {title}" + (" · 새 신호" if s.is_new else ""),
            f"  {s.url}"]


def radar_markdown(d):
    out = [f"# OSINT 데스크 리포트 {_t(d['now'], '%Y-%m-%d %H:%M')}", "",
           f"- 조회 기간 최근 {d['lookback']}일 · 추적 대상 관련 신호 {len(d['signals'])}건(새 신호 {len(d['new'])}건)"
           f" · 발제 후보 {len(d['cands'])}건",
           "- AI 발제문: " + ("켜짐(아래 'AI 발제문' 참고)" if d.get("use_ai") else
                           "꺼짐 — 자동 정리만 했다. AI를 고르면 기사 앵글·가제 초안이 붙는다"),
           ]
    if d.get("translation"):
        out.append(f"- {d['translation']}")
    out += ["- 국내 보도 건수는 네이버 자동 검색 기준이다. '선제 보도 후보'는 확인 취재 뒤 데스크가 판단한다.", ""]

    ai_parts = {}
    for label, text in (d["ai"] or {}).items():
        for cid, part in split_ai(text).items():
            ai_parts.setdefault(cid, []).append((label, part))

    out += ["## 발제 후보", ""]
    if not d["cands"]:
        out.append("이번 수집에서는 후보가 없다.")
    for c in d["cands"]:
        out += [f"### {c.id} · {c.entity}" + (f" · {c.location}" if c.location else ""),
                f"점수 {c.score} — {' · '.join(c.reasons)}", "", d["skeletons"][c.id], ""]
        for label, part in ai_parts.get(c.id, []):
            body = re.sub(r"^###\s*후보\s*C\d+\s*", "", part).strip()
            out += [f"[{label} 발제문 초안 — 원문 확인 후 사용]", body, ""]
        out.append("근거 신호 전체")
        for s in c.signals[:8]:
            out += _signal_line(s)
        out.append("")

    for label, text in (d["ai"] or {}).items():
        if not split_ai(text):   # 후보별로 나뉘지 않은 응답은 통째로
            out += ["---", "", f"## {label} 발제문 (초안 · 원문 확인 후 사용)", "", text, ""]

    out += ["---", "", "## 채널 상태", ""]
    for st in d["status"].values():
        out.append(f"- {st['name']}: {st['count']}건 ({st['sec']}초)" + (f" — 오류: {st['error']}" if st["error"] else ""))
    out += ["", "## 새 신호 전체", ""]
    for s in sorted(d["new"], key=lambda s: (s.channel, -(s.published.timestamp() if s.published else 0))):
        line = _signal_line(s)
        line[0] += f" — {', '.join(s.entities)}" + (f" / {', '.join(s.locations)}" if s.locations else "")
        out += line
    return "\n".join(out) + "\n"


def reverse_markdown(d):
    out = [f"# 역추적 리포트 {_t(d['now'], '%Y-%m-%d %H:%M')}", ""]
    if d.get("url"):
        out += ["- 대상 기사", f"  {d['url']}"]
    out += ["", "## AI 역설계", ""]
    for label, text in (d.get("ai") or {}).items():
        out += [f"### {label}", "", text, ""]
    if not d.get("ai"):
        out.append("AI를 켜지 않아 1차 출처 후보 목록만 정리했다.")
    out += ["", "## 1차 출처 후보", ""]
    for i, s in enumerate(d["sources"], 1):
        out += [f"- [S{i}] {_t(s.published)} [{s.channel}] {s.source} · {s.meta.get('ko_title') or s.title}",
                f"  {s.url}"]
    out += ["", "## 대상 기사 원문(앞부분)", "", (d.get("article") or "")[:3000]]
    return "\n".join(out) + "\n"
