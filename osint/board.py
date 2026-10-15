"""OSINT 레이더·역추적 결과 → 결과 화면 데이터. 자료를 출처 성격(정부·공공/기업 발표/언론)과
채널별로 나눠 한눈에 보이게 한다."""

import re

from balje.board import Board, bullets, checks, h, kv, link, load, note, p, save, sub, title, when  # noqa: F401

from . import classify, report

SIG_COLS = [("날짜", 92, False), ("구분", 130, False), ("기업·대상", 130, False), ("제목(번역)", 430, True),
            ("출처", 160, False), ("새", 34, False)]
CAND_COLS = [("순위", 46, False), ("판정", 120, False), ("기업", 120, False), ("지역", 110, False),
             ("핵심 내용", 400, True), ("근거 채널", 170, False), ("점수", 52, False)]
STATUS_COLS = [("채널", 170, False), ("성격", 80, False), ("수집", 56, False), ("표시", 56, False),
               ("소요(초)", 66, False), ("상태", 360, True)]
DOC_COLS = [("항목", 560, True)]


def _ch_name(config, key):
    return config["osint"]["channels"].get(key, {}).get("name") or {
        "news_en": "외신 검색", "news_zh": "중국어 검색"}.get(key, key)


def _short(text, n=1500):
    text = " ".join((text or "").split())
    return text[:n] + ("…" if len(text) > n else "")


def signal_detail(s, config, cand_ids=()):
    kind = classify.kind_of(s)
    d = [title(s.meta.get("ko_title") or s.title)]
    if s.meta.get("ko_title"):
        d.append(dict(sub("원문 제목: " + s.title), keep=True))   # 원문 대조용이라 번역하지 않음
    d.append(link(f"{s.source} 원문", s.url, s.meta.get("domain", "")))
    d.append(kv([
        ("구분", f"{classify.kind_label(kind)} › {_ch_name(config, s.channel)}"),
        ("출처", s.source), ("사이트", s.meta.get("domain", "")),
        ("날짜", when(s.published, "%Y-%m-%d %H:%M") if s.published else "날짜 미상"),
        ("기업·대상", ", ".join(s.entities)), ("지역", ", ".join(s.locations)),
        ("새 신호", "예(이번에 처음 잡힘)" if s.is_new else f"아니오(처음 본 때 {when(s.first_seen, '%m-%d %H:%M')})"),
        ("발제 후보", ", ".join(cand_ids)),
        # 채널별 추가 정보
        ("공시 종류", s.meta.get("form", "")), ("회사", s.meta.get("company", "")),
        ("사건", s.meta.get("case", "")), ("법원", s.meta.get("court", "")), ("사건번호", s.meta.get("docket", "")),
        ("리콜 번호", s.meta.get("campaign", "")), ("부품", s.meta.get("component", "")),
        ("대상 차량", ", ".join(s.meta.get("vehicles", [])[:12])),
        ("기관", ", ".join(s.meta.get("agencies", []))), ("문서 종류", s.meta.get("doc_type", "")),
        ("정책 주제", s.meta.get("topic", "")),
    ]))
    if s.meta.get("ko_text"):
        d += [h("요약(번역)"), p(s.meta["ko_text"])]
    if s.text:
        d += [h("원문 요약" if s.meta.get("ko_text") else "요약"),
              dict(p(_short(s.text)), keep=bool(s.meta.get("ko_text")))]
    if s.meta.get("doc_text"):
        d += [h("1차 출처 원문 앞부분"), p(_short(s.meta["doc_text"], 2500))]
    if s.meta.get("index"):
        d.append(link("공시 목록(첨부 전체) 열기", s.meta["index"]))
    if s.query:
        d.append(note("검색어: " + s.query))
    return d


def cand_detail(c, config, ai_parts):
    from .radar import _when, checklist, verdict
    short, tag = verdict(c)
    s0 = c.lead
    d = [title(f"{c.entity}" + (f" · {c.location}" if c.location else "") + f" — {s0.meta.get('ko_title') or s0.title}"),
         sub(f"🚨 {tag} · 점수 {c.score}" + (f" — {' · '.join(c.reasons)}" if c.reasons else "")
             + ("" if any("모자이크" in r for r in c.reasons) else
                (" · 모자이크(서로 다른 출처 결합)" if c.kind == "mosaic" else " · 단일 신호")))]
    d.append(h("핵심 팩트(원문 기준)"))
    d.append(bullets([(x.meta.get("ko_title") or x.title) + (f" — {x.meta['ko_text']}" if x.meta.get("ko_text") else "")
                      for x in c.signals[:3]]))
    d.append(h(f"출처 {len(c.signals)}건"))
    for i, x in enumerate(c.signals[:8], 1):
        d.append(link(f"{i}차 · {x.meta.get('ko_title') or x.title}", x.url,
                      f"{classify.kind_label(classify.kind_of(x))} › {_ch_name(config, x.channel)} · {x.source} · {_when(x)}"))
    dom = c.domestic
    d.append(h("국내 보도(네이버 자동 검색)"))
    if dom is None:
        d.append(p("자동 검색 불가 — [설정]에 네이버 키를 넣으면 같은 내용 국내 기사가 있는지 센다."))
    else:
        d.append(p(f"최근 {dom['days']}일 '{' / '.join(dom['queries'])}' 검색 {dom['count']}건"
                   + (" → 국내에 아직 안 나온 내용일 수 있다. 확인 취재 뒤 판단." if dom["count"] == 0 else "")))
        for press, _, t, url in dom["examples"][:3]:
            d.append(link(t, url, press))
    d += [h("✅ 체크리스트"), checks(checklist(c))]
    for label, part in ai_parts.get(c.id, []):
        body = re.sub(r"^###\s*후보\s*C\d+\s*", "", part).strip()
        d += [h(f"{label} 발제문 초안"), note("초안이다. 원문과 대조한 뒤 쓴다."), p(body)]
    docs = [x for x in c.signals if x.meta.get("doc_text")]
    for x in docs[:2]:
        d += [h(f"원문 앞부분 — {x.source}"), p(_short(x.meta["doc_text"], 2000))]
    return d, short


def radar_board(data, config):
    now = data["now"]
    b = Board("radar", f"OSINT 레이더 {when(now, '%Y-%m-%d %H:%M')}", now)
    b.columns("cand", CAND_COLS)
    b.columns("sig", SIG_COLS)
    b.columns("status", STATUS_COLS)
    b.columns("doc", DOC_COLS)
    signals, cands, status = data["signals"], data["cands"], data["status"]

    by_kind = {k: 0 for k in classify.KIND_ORDER}
    for s in signals:
        by_kind[classify.kind_of(s)] += 1
    b.summary(f"최근 {data['lookback']}일 · 자료 {len(signals)}건(새 신호 {len(data['new'])}건) · "
              f"발제 후보 {len(cands)}건")
    b.summary(" · ".join(f"{classify.kind_label(k)} {by_kind[k]}건" for k in classify.KIND_ORDER))
    errors = [f"{st['name']}" for st in status.values() if st.get("error")]
    if errors:
        b.summary("수집 실패: " + ", ".join(errors) + " → 왼쪽 '수집 상태'에서 이유 확인")
    b.summary(data.get("translation", ""))
    b.summary("AI 발제문: " + ("켜짐" if data.get("use_ai") else "꺼짐(자동 정리만. AI를 고르면 앵글·가제 초안이 붙는다)"))
    b.summary("국내 보도 건수는 네이버 자동 검색 기준. '선제 보도 후보'는 확인 취재 뒤 데스크가 판단한다.")

    b.group("cand", "★ 발제 후보", "cand")
    b.group("new", "새로 잡힌 자료", "sig")
    b.group("all", "전체 자료", "sig")
    for k in classify.KIND_ORDER:
        b.group(k, classify.kind_label(k), "sig", parent="all")
    # 실행한 채널은 0건이어도 보이게(어디서 안 나왔는지 알 수 있게)
    for key, st in status.items():
        k = classify.CHANNEL_KIND.get(key, "media")
        b.group(f"{k}/{key}", st["name"] + (" ⚠" if st.get("error") else ""), "sig", parent=k)

    ai_parts = {}
    for label, text in (data.get("ai") or {}).items():
        for cid, part in report.split_ai(text).items():
            ai_parts.setdefault(cid, []).append((label, part))

    in_cand = {}
    for c in cands:
        for s in c.signals:
            in_cand.setdefault(s.uid, []).append(c.id)
    for c in cands:
        detail, short = cand_detail(c, config, ai_parts)
        b.row(c.id, ["cand"], [c.id, short, c.entity, c.location or "-",
                               c.lead.meta.get("ko_title") or c.lead.title,
                               ", ".join(dict.fromkeys(_ch_name(config, x.channel) for x in c.signals)), c.score],
              detail, url=c.lead.url, new=any(s.is_new for s in c.signals))

    for s in sorted(signals, key=lambda s: -(s.published.timestamp() if s.published else 0)):
        k = classify.kind_of(s)
        gkey = f"{k}/{s.channel}"
        if gkey not in b._keys:
            default = classify.CHANNEL_KIND.get(s.channel, "media")
            label = _ch_name(config, s.channel) + (f" 중 {classify.kind_label(k)}" if k != default else "")
            b.group(gkey, label, "sig", parent=k)
        groups = ["all", k, gkey] + (["new"] if s.is_new else [])
        ents = ", ".join(s.entities[:2]) + (" 외" if len(s.entities) > 2 else "")
        if not ents and s.meta.get("topic"):
            ents = "정책: " + s.meta["topic"]
        b.row(s.uid, groups, [when(s.published), _ch_name(config, s.channel), ents or "-",
                              s.meta.get("ko_title") or s.title, s.source, "●" if s.is_new else ""],
              signal_detail(s, config, in_cand.get(s.uid, [])), url=s.url, new=s.is_new)

    for label, text in (data.get("ai") or {}).items():
        if not report.split_ai(text):    # 후보별로 나뉘지 않은 응답은 통째로
            b.group("ai", "AI 발제문", "doc")
            b.row(f"ai-{label}", ["ai"], [f"{label} 발제문 (초안 · 원문 확인 후 사용)"], [title(f"{label} 발제문"), p(text)])

    b.group("status", "수집 상태", "status")
    shown = {}
    for s in signals:
        shown[s.channel] = shown.get(s.channel, 0) + 1
    for key, st in status.items():
        k = classify.CHANNEL_KIND.get(key, "media")
        state = ("오류: " + st["error"]) if st.get("error") else ("정상" if st["count"] else "정상(해당 기간 자료 없음)")
        d = [title(st["name"]), kv([("성격", classify.kind_label(k)), ("수집", f"{st['count']}건"),
                                    ("추적 대상 관련(표시)", f"{shown.get(key, 0)}건"), ("소요", f"{st['sec']}초"),
                                    ("상태", state)])]
        if not st.get("error") and st["count"] and not shown.get(key):
            d.append(note("수집은 됐지만 추적 대상 기업·지역과 맞는 자료가 없어 표시하지 않았다. "
                          "[추적 대상 편집]에서 기업 표기를 늘리면 잡힐 수 있다."))
        b.row(f"status-{key}", ["status"], [st["name"], classify.kind_label(k), st["count"], shown.get(key, 0),
                                            st["sec"], state], d, warn=bool(st.get("error")))
    return b.data


# ---------------------------------------------------------------- 역추적

def reverse_board(d, config):
    now = d["now"]
    b = Board("reverse", f"역추적·팩트체크 {when(now, '%Y-%m-%d %H:%M')}", now)
    b.columns("sig", SIG_COLS)
    b.columns("doc", DOC_COLS)
    sources = d["sources"]
    b.summary(f"1차 출처 후보 {len(sources)}건 · AI " + (", ".join(d["ai"]) if d.get("ai") else "꺼짐"))
    ext = d.get("extract") or {}
    qs = ext.get("queries_en", []) + ext.get("queries_zh", [])
    if qs:
        b.summary("검색어: " + " / ".join(qs))

    b.group("ai", "AI 역설계", "doc")
    b.group("claims", "기사 속 주장", "doc")
    b.group("src", "1차 출처 후보", "sig")
    for k in classify.KIND_ORDER:
        b.group(f"src/{k}", classify.kind_label(k), "sig", parent="src")
    b.group("article", "대상 기사", "doc")

    if not d.get("ai"):
        b.row("ai-none", ["ai"], ["AI를 켜지 않아 1차 출처 후보만 찾았습니다"],
              [title("AI 역설계 없음"), p("AI를 고르고 다시 실행하면 주장별로 원문과 대조한 리포트가 붙습니다.")])
    for label, text in (d.get("ai") or {}).items():
        b.row(f"ai-{label}", ["ai"], [f"{label} 역설계 리포트"], [title(f"{label} 역설계 리포트"),
                                                              note("출처 번호 [S1]… 는 '1차 출처 후보' 목록 순서다."), p(text)])
    for i, c in enumerate(ext.get("claims") or [], 1):
        if not isinstance(c, dict):
            c = {"text": str(c)}
        cid = c.get("id") or f"K{i}"
        b.row(f"claim-{cid}", ["claims"], [f"{cid}. {c.get('text', '')}"],
              [title(f"{cid}. {c.get('text', '')}"),
               kv([("수치", ", ".join(c.get("numbers") or [])), ("기사가 밝힌 출처", c.get("attributed_to", ""))])])
    for i, s in enumerate(sources, 1):
        k = classify.kind_of(s)
        b.row(f"S{i}", ["src", f"src/{k}"], [when(s.published), f"S{i} · {_ch_name(config, s.channel)}",
                                             ", ".join(s.entities[:2]) or "-", s.meta.get("ko_title") or s.title,
                                             s.source, ""], signal_detail(s, config), url=s.url)
    art = [title("대상 기사")]
    if d.get("url"):
        art.append(link("기사 열기", d["url"]))
    art.append(p((d.get("article") or "")[:6000]))
    b.row("article", ["article"], ["대상 기사 본문"], art, url=d.get("url", ""))
    return b.data
