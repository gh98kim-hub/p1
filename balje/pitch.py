"""발제 초안 생성. 규칙 기반 메모는 항상, Claude 초안은 --ai 옵션일 때만."""

import re
from pathlib import Path

GENERIC_CHECKS = ["보도 내용 원문(회사·기관 발표) 확인", "회사 측 공식 입장 확인"]


def rule_based_notes(cluster, config):
    """이슈 하나에 대한 데스크 보고용 메모(각도·취재 포인트). 사실은 기사 목록에서만 가져온다."""
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
        angles.append("[해석] 다수 매체가 이미 보도. 단순 전달보다 경제지 시각의 해석·후속 필요")
    if cluster.numbers:
        checks.append("기사에 나온 수치(" + ", ".join(cluster.numbers[:4]) + ") 원자료 대조")
    if not angles:
        angles.append("[기본] 사실 전달형. 추가 각도는 취재 후 판단")

    checks = list(dict.fromkeys(checks + GENERIC_CHECKS))
    status = []
    if cluster.exclusive:
        status.append("타사 단독")
    if cluster.my_press_covered:
        status.append("자사 기보도")
    status.append("신규" if cluster.is_new else "지속")
    return {"angles": angles, "checks": checks, "status": status}


# ---------------------------------------------------------------- Claude 발제안

SYSTEM_PROMPT = """너는 경제지 자동차 담당 기자의 아침 발제를 돕는 데스크 보조다.

원칙:
- 아래 [자료]에 있는 내용만 쓴다. 자료에 없는 사실·수치·인물·발언·배경지식은 절대 쓰지 않는다.
- 자료로 확인되지 않는 부분은 추정하지 말고 '추가 확인 필요' 항목으로 돌린다.
- 근거가 되는 자료 번호(예: [A03], [M1])를 문장 끝에 붙인다.
- 다른 매체 기사 문장을 그대로 옮기지 않는다. 요지를 새로 정리한다.
- 문체는 연합뉴스처럼 직관적이고 건조하게. 과장·수사·감탄 표현 금지.
- 부장에게 올리는 발제처럼 핵심부터, 짧고 단정하게 쓴다.

{style}
"""

USER_TEMPLATE = """오늘 발제 후보를 최대 {max_pitches}개 골라 아래 형식으로 써라.
점수가 높은 이슈를 우선하되, 다른 매체가 이미 많이 쓴 이슈는 경제지만의 해석·후속 각도가 있을 때만 고른다.
'자사 기보도' 이슈는 후속 각도가 분명할 때만 고른다.

형식(발제마다 반복):
## 발제 N. (가제)
- 한 줄 요지:
- 왜 지금:
- 근거: (자료 번호와 함께 2~4줄)
- 취재 포인트: (누구에게 무엇을 확인할지)
- 추가로 필요한 자료: (기자에게 요청할 자료)
- 데스크 보고용 한 줄:

마지막에 '## 이번에 고르지 않은 이슈'로 제외 이유를 이슈 번호와 함께 한 줄씩 적어라.

[자료]
{materials}
"""


def build_materials_text(clusters, materials, notes, max_clusters):
    lines = []
    for c in clusters[:max_clusters]:
        n = notes[c.id]
        lines.append(f"### 이슈 {c.id} (점수 {c.score} / {', '.join(n['status'])} / 매체 {len(c.press)}곳)")
        if c.angles:
            lines.append("분류: " + ", ".join(c.angles))
        for a in c.articles[:8]:
            when = a.published.strftime("%m-%d %H:%M") if a.published else "시각 미상"
            lines.append(f"[{a.id}] {a.press} | {when} | {a.title}")
            if a.description:
                lines.append(f"    요약: {a.description}")
        if len(c.articles) > 8:
            lines.append(f"    (외 {len(c.articles) - 8}건)")
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


def ai_pitches(clusters, materials, notes, config):
    """Claude로 발제안 초안을 쓴다. 실패하면 예외 대신 안내 문구를 돌려준다."""
    try:
        import anthropic
    except ImportError:
        return "> AI 발제안을 쓰려면 `pip install anthropic` 후 ANTHROPIC_API_KEY를 설정하세요."

    ai = config["ai"]
    system = SYSTEM_PROMPT.format(style=load_style(ai.get("style_file")))
    user = USER_TEMPLATE.format(
        max_pitches=ai.get("max_pitches", 5),
        materials=build_materials_text(clusters, materials, notes, ai.get("max_clusters", 15)),
    )

    client = anthropic.Anthropic()
    try:
        with client.beta.messages.stream(
            model=ai.get("model", "claude-opus-5-5"),
            max_tokens=32000,
            thinking={"type": "adaptive"},
            output_config={"effort": ai.get("effort", "high")},
            # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError:
        return "> AI 발제안 실패: API 키가 올바르지 않습니다(ANTHROPIC_API_KEY 확인)."
    except anthropic.RateLimitError:
        return "> AI 발제안 실패: 호출 한도 초과. 잠시 후 다시 실행하세요."
    except anthropic.APIStatusError as e:
        return f"> AI 발제안 실패: API 오류({e.status_code}) {e.message}"
    except anthropic.APIConnectionError:
        return "> AI 발제안 실패: 네트워크 연결을 확인하세요."

    if response.stop_reason == "refusal":
        return "> AI 발제안 실패: 모델이 응답을 거절했습니다. 자료 구성을 확인하세요."
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "max_tokens":
        text += "\n\n> (출력 길이 제한으로 중간에 끊겼습니다.)"
    return text
