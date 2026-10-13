"""발제 메모(규칙 기반)와 AI 발제안. 사실은 수집 기사·기자 제공 자료에서만 가져온다."""

import re
import threading
from pathlib import Path

from .analyze import _contains
from .llm import PROVIDERS

GENERIC_CHECKS = ["보도 내용 원문(회사·기관 발표) 확인", "회사 측 공식 입장 확인"]


def _cluster_text(cluster):
    return " ".join(f"{a.title} {a.description}" for a in cluster.articles)


def twists_for(cluster, config):
    """이미 나온 기사에서 틀어 쓸 시각. 기사에 이미 나온 시각은 covered=True."""
    text = _cluster_text(cluster)
    specs = []
    for name in cluster.angles:
        specs += config.get("angles", {}).get(name, {}).get("twists", [])
    specs += config.get("generic_twists", [])
    out, seen = [], set()
    for t in specs:
        if t["view"] in seen:
            continue
        seen.add(t["view"])
        covered = any(_contains(text, w) for w in t.get("covered_if", []))
        out.append({"view": t["view"], "covered": covered})
    # 아직 안 나온 시각 위주로 최대 5개
    fresh = [t for t in out if not t["covered"]]
    done = [t for t in out if t["covered"]]
    return fresh[:4] + done[:5 - min(len(fresh), 4)]


def release_review(cluster, trend_cats, twists):
    """보도자료성 이슈의 발제 가치 판단."""
    kind = cluster.release_kind
    reasons = list(cluster.release_signals)
    angles = []
    in_trend = list(trend_cats)
    if in_trend:
        angles.append(f"다른 브랜드의 같은 움직임과 묶어 업계 흐름 기사로({', '.join(in_trend)})")
    if cluster.numbers:
        angles.append("발표 수치(" + ", ".join(cluster.numbers[:3]) + ") 검증: 원자료·과거 발표와 대조")
    angles += [t["view"] for t in twists if not t["covered"]][:2]

    if kind == "홍보성":
        verdict = "묶음 기획 소재" if in_trend else "단신 또는 생략"
        if not in_trend:
            reasons.append("홍보성 발표 단독으로는 기사 가치 낮음")
    elif cluster.numbers or len(cluster.press) >= 3 or in_trend:
        verdict = "앵글 검토 가치 있음"
    else:
        verdict = "단신"
    return {"kind": kind, "verdict": verdict, "reasons": reasons, "angles": angles}


def rule_based_notes(cluster, config, trends=None):
    """이슈 하나에 대한 데스크 보고용 메모(각도·취재 포인트·틀어보기·보도자료 판단)."""
    angles_cfg = config.get("angles", {})
    angles, checks = [], []
    for name in cluster.angles:
        spec = angles_cfg.get(name, {})
        if spec.get("angle"):
            angles.append(f"[{name}] {spec['angle']}")
        checks.extend(spec.get("checks", []))

    if cluster.exclusive:
        presses = ", ".join(sorted({a.press for a in cluster.exclusive if a.press}))
        angles.insert(0, f"[후속] 타사 단독({presses}) 사실관계 확인 후 추가 취재")
        checks.insert(0, "단독 보도 내용 회사 측 확인(사실 여부·추가 내용)")
    if len(cluster.press) >= 5 and not cluster.exclusive:
        angles.append("[해석] 다수 매체가 이미 보도. 단순 전달보다 아래 '틀어보기' 시각으로 차별화")
    if cluster.numbers:
        checks.append("기사에 나온 수치(" + ", ".join(cluster.numbers[:4]) + ") 원자료 대조")
    if not angles:
        angles.append("[기본] 사실 전달형. 추가 각도는 취재 후 판단")

    checks = list(dict.fromkeys(checks + GENERIC_CHECKS))
    status = []
    if cluster.foreign:
        status.append("외신")
    if cluster.exclusive:
        status.append("타사 단독")
    if cluster.release_kind:
        status.append(f"보도자료({cluster.release_kind})")
    if cluster.my_press_covered:
        status.append("자사 기보도")
    status.append("신규" if cluster.is_new else "지속")

    twists = twists_for(cluster, config)
    trend_cats = [t["category"] for t in (trends or []) if any(c is cluster for c in t["clusters"])]
    release = release_review(cluster, trend_cats, twists) if cluster.release_kind else None
    return {"angles": angles, "checks": checks, "status": status, "twists": twists,
            "release": release, "trends": trend_cats}


# ---------------------------------------------------------------- AI 발제안

SYSTEM_PROMPT = """너는 경제지 자동차 담당 기자의 아침 발제를 돕는 데스크 보조다.

원칙:
- 아래 [자료]에 있는 내용만 쓴다. 자료에 없는 사실·수치·인물·발언·배경지식은 절대 쓰지 않는다.
- 자료로 확인되지 않는 부분은 추정하지 말고 '추가 확인 필요' 항목으로 돌린다.
- 근거가 되는 자료 번호(예: [A003], [M1])를 문장 끝에 붙인다.
- 다른 매체 기사 문장을 그대로 옮기지 않는다. 요지를 새로 정리한다.
- 새 시각을 제안할 때는 '무엇을 확인하면 기사가 되는지'로 쓴다. 확인 전 내용을 사실처럼 쓰지 않는다.
- '외신' 표시 이슈는 영문 기사다. 국내 발제의 배경·후속 소재로 쓰고, 인용할 때는 매체명을 밝힌다.
- 문체는 연합뉴스처럼 직관적이고 건조하게. 과장·수사·감탄 표현 금지.
- 부장에게 올리는 발제처럼 핵심부터, 짧고 단정하게 쓴다.

{style}
"""

USER_TEMPLATE = """아래 자료로 세 가지를 써라.

# 1. 오늘의 발제안 (최대 {max_pitches}개)
점수가 높은 이슈를 우선하되, 다른 매체가 이미 많이 쓴 이슈는 경제지만의 해석·후속 각도가 있을 때만 고른다.
'자사 기보도' 이슈는 후속 각도가 분명할 때만 고른다. '묶어보기 후보'로 기획 발제를 만들어도 된다.

형식(발제마다 반복):
## 발제 N. (가제)
- 한 줄 요지:
- 왜 지금:
- 근거: (자료 번호와 함께 2~4줄)
- 취재 포인트: (누구에게 무엇을 확인할지)
- 추가로 필요한 자료: (기자에게 요청할 자료)
- 데스크 보고용 한 줄:

# 2. 보도자료 점검
'보도자료' 표시가 붙은 이슈마다 한 덩어리씩:
## 이슈 번호 · 한 줄 요약
- 판단: 발제 가능 / 묶음 기획 소재 / 단신 / 생략 중 하나
- 이유: (자료 번호와 함께)
- 살릴 앵글: (있으면 1~2개. 무엇을 더 확인하면 기사가 되는지)

# 3. 틀어보기
이미 여러 매체가 보도한 이슈(매체 3곳 이상) 중 3개를 골라 각각(외신에서 국내 시각으로 풀 소재가 있으면 함께):
## 이슈 번호 · 한 줄 요약
- 이미 나온 시각: (기존 기사들이 공통으로 다룬 내용)
- 새 시각: (2~3개. 같은 소재를 다르게 볼 방법)
- 새 시각마다 필요한 취재·자료:

마지막에 '# 이번에 고르지 않은 이슈'로 제외 이유를 이슈 번호와 함께 한 줄씩 적어라.

[자료]
{materials}
"""


def build_materials_text(clusters, materials, notes, max_clusters, trends=(), max_foreign=6, body_chars=1500):
    lines = []
    domestic = [c for c in clusters if not c.foreign][:max_clusters]
    foreign = sorted((c for c in clusters if c.foreign), key=lambda c: -c.score)[:max_foreign]
    for c in domestic + foreign:
        n = notes[c.id]
        lines.append(f"### 이슈 {c.id} (점수 {c.score} / {', '.join(n['status'])} / 매체 {len(c.press)}곳)")
        if c.angles:
            lines.append("분류: " + ", ".join(c.angles))
        if c.brands:
            lines.append("브랜드: " + ", ".join(c.brands))
        if c.release_signals:
            lines.append("보도자료 신호: " + " / ".join(c.release_signals))
        fresh = [t["view"] for t in n["twists"] if not t["covered"]]
        if fresh:
            lines.append("참고(기사에 아직 안 보이는 시각): " + " / ".join(fresh[:4]))
        for a in c.articles[:8]:
            when = a.published.strftime("%m-%d %H:%M") if a.published else "시각 미상"
            lines.append(f"[{a.id}] {a.press} | {when} | {a.title}")
            if a.description:
                lines.append(f"    요약: {a.description}")
            if a.body:
                body = " ".join(a.body.split())
                lines.append(f"    본문: {body[:body_chars]}{'…' if len(body) > body_chars else ''}")
        if len(c.articles) > 8:
            lines.append(f"    (외 {len(c.articles) - 8}건)")
        lines.append("")
    if trends:
        lines.append("### 묶어보기 후보(서로 다른 브랜드의 같은 유형 이슈)")
        for t in trends:
            ids = ", ".join(c.id for c in t["clusters"])
            lines.append(f"- {t['category']}: 브랜드 {', '.join(t['brands'])} / 이슈 {ids}")
        lines.append("")
    for i, m in enumerate(materials, 1):
        lines.append(f"### 기자 제공 자료 [M{i}] {m['name']}")
        lines.append(m["text"])
        lines.append("")
    return "\n".join(lines)


def load_style(path):
    p = Path(path) if path else None
    if p and p.exists():
        text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S).strip()
        return "[하우스 스타일]\n" + text if text else ""
    return ""


def build_prompts(clusters, materials, notes, config, trends=()):
    ai = config["ai"]
    system = SYSTEM_PROMPT.format(style=load_style(ai.get("style_file")))
    user = USER_TEMPLATE.format(
        max_pitches=ai.get("max_pitches", 5),
        materials=build_materials_text(clusters, materials, notes, ai.get("max_clusters", 15), trends),
    )
    return system, user


def ai_pitches(clusters, materials, notes, config, trends=()):
    """설정한 AI(claude/gemini/both)로 초안을 쓴다. {이름: 결과 텍스트}를 돌려준다."""
    provider = config["ai"].get("provider", "claude")
    names = ["claude", "gemini"] if provider == "both" else [provider]
    names = [n for n in names if n in PROVIDERS]
    if not names:
        return {"AI": f"> 알 수 없는 AI 설정: {provider}"}
    system, user = build_prompts(clusters, materials, notes, config, trends)

    results = {}

    def work(name):
        label, fn = PROVIDERS[name]
        results[label] = fn(system, user, config)

    threads = [threading.Thread(target=work, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {PROVIDERS[n][0]: results[PROVIDERS[n][0]] for n in names}
