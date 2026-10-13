"""설정 로드. config.json이 있으면 기본값 위에 덮어쓴다."""

import json
from pathlib import Path

DEFAULTS = {
    # 네이버 뉴스 검색어. 키워드별로 최신순 100건씩 가져온다.
    "keywords": ["현대차", "기아", "전기차", "자동차 관세", "완성차"],
    # 키워드별로 가져올 페이지 수(1페이지=100건)
    "pages_per_keyword": 1,
    # 최근 몇 시간 기사만 볼지
    "lookback_hours": 24,
    # 우리 매체 이름. 이미 보도한 이슈를 '자사 기보도'로 표시한다.
    "my_press": "",
    # 출입처·관심 대상. 제목/요약에 등장하면 가중치를 준다.
    "watch_terms": [
        "현대차", "현대자동차", "기아", "제네시스", "KG모빌리티", "르노코리아",
        "한국GM", "GM", "테슬라", "BYD", "토요타", "벤츠", "BMW",
        "현대모비스", "현대글로비스", "LG에너지솔루션", "삼성SDI", "SK온",
    ],
    # 발제 각도 분류. 제목/요약에 단어가 들어가면 해당 각도를 붙인다.
    "angles": {
        "실적": {
            "terms": ["실적", "영업이익", "매출", "순이익", "어닝", "컨센서스"],
            "angle": "실적 해부: 숫자 뒤의 원인(믹스·환율·인센티브) 짚기",
            "checks": ["회사 IR 자료 원문 확보", "전년·전분기 대비 증감 확인", "증권가 전망치 자료 요청"],
        },
        "판매": {
            "terms": ["판매", "점유율", "판매량", "수출", "내수", "등록"],
            "angle": "판매 데이터 기사: 추이·순위 변화 중심",
            "checks": ["월별 판매 원자료 확보", "브랜드·차종별 세부 수치 확인"],
        },
        "관세·통상": {
            "terms": ["관세", "통상", "무역", "IRA", "보조금", "환율", "FTA"],
            "angle": "거시 변수 영향 분석: 업체별 손익 영향 추정",
            "checks": ["정부·업계 공식 발표 원문 확인", "업체별 영향 규모 자료 요청"],
        },
        "신차": {
            "terms": ["출시", "신차", "공개", "사전계약", "풀체인지", "페이스리프트"],
            "angle": "신차 경쟁력 점검: 가격·사양·경쟁 모델 비교",
            "checks": ["가격표·제원표 확보", "시승 일정 확인"],
        },
        "리콜·품질": {
            "terms": ["리콜", "결함", "무상수리", "화재", "급발진", "품질"],
            "angle": "소비자 영향 점검: 대상 차량 규모·조치 내용",
            "checks": ["국토부·제조사 리콜 공지 원문 확인", "대상 대수·차종 확인"],
        },
        "노사": {
            "terms": ["노조", "파업", "임단협", "임금협상", "특근"],
            "angle": "생산 차질 규모 점검",
            "checks": ["노사 양측 입장 확인", "생산 손실 대수 자료 요청"],
        },
        "전동화·배터리": {
            "terms": ["전기차", "배터리", "충전", "하이브리드", "수소", "캐즘"],
            "angle": "전동화 전략 흐름: 투자·라인업 변화",
            "checks": ["투자 규모·일정 공식 자료 확인", "판매 비중 수치 확보"],
        },
        "지배구조·인사": {
            "terms": ["인사", "사장", "부회장", "회장", "지배구조", "지분"],
            "angle": "인사·지배구조 의미 해석",
            "checks": ["공시·보도자료 원문 확인", "인사 배경 취재"],
        },
    },
    # 출력 위치
    "output_dir": "output",
    # 한번 본 기사 기록(신규/지속 이슈 판별용)
    "history_file": "data/history.json",
    "history_days": 14,
    # Claude 발제안 설정
    "ai": {
        "model": "claude-opus-5-5",
        "effort": "high",
        "max_pitches": 5,
        "max_clusters": 15,
        "style_file": "style/house_style.md",
    },
    # 도메인 → 매체명 추가 매핑(기본 표에 없는 매체)
    "press_map": {},
    # API 키(비워두면 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET / ANTHROPIC_API_KEY 사용)
    "naver_client_id": "",
    "naver_client_secret": "",
    "anthropic_api_key": "",
}


def _merge(base, override):
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path="config.json"):
    p = Path(path)
    if not p.exists():
        return _merge(DEFAULTS, {})
    with p.open(encoding="utf-8") as f:
        return _merge(DEFAULTS, json.load(f))


def save_config(values, path="config.json"):
    """기존 config.json에 values를 덮어써 저장한다(GUI 설정 저장용)."""
    p = Path(path)
    current = {}
    if p.exists():
        with p.open(encoding="utf-8") as f:
            current = json.load(f)
    current.update(values)
    with p.open("w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
