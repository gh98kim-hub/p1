"""설정 로드. config.json이 있으면 기본값 위에 덮어쓴다."""

import json
from pathlib import Path

def _brand(name, query=None, aliases=None):
    return {"name": name, "query": query or name, "aliases": aliases or [name]}


DEFAULTS = {
    # 네이버 뉴스 검색어(주제). 브랜드 검색어는 아래 brands에서 자동으로 더한다.
    "keywords": ["완성차", "자동차 관세", "전기차", "수입차", "자동차 판매"],
    # 브랜드 전체를 검색어에 넣을지
    "search_brands": True,
    # 브랜드 목록. query=네이버 검색어, aliases=기사에서 브랜드를 알아보는 표기
    "brands": [
        _brand("현대차", aliases=["현대차", "현대자동차", "Hyundai"]),
        _brand("기아", aliases=["기아", "Kia"]),
        _brand("제네시스", aliases=["제네시스", "Genesis"]),
        _brand("KG모빌리티", aliases=["KG모빌리티", "KGM"]),
        _brand("르노코리아", aliases=["르노코리아", "르노"]),
        _brand("한국GM", aliases=["한국GM", "GM한국사업장", "쉐보레", "GMC", "General Motors", "Chevrolet"]),
        _brand("테슬라", aliases=["테슬라", "Tesla"]),
        _brand("BYD"),
        _brand("벤츠", aliases=["벤츠", "메르세데스", "Mercedes"]),
        _brand("BMW"),
        _brand("MINI", query="MINI 코리아", aliases=["MINI"]),
        _brand("아우디", aliases=["아우디", "Audi"]),
        _brand("폭스바겐", aliases=["폭스바겐", "Volkswagen"]),
        _brand("볼보", aliases=["볼보", "Volvo"]),
        _brand("토요타", aliases=["토요타", "도요타", "Toyota"]),
        _brand("렉서스", aliases=["렉서스", "Lexus"]),
        _brand("혼다", aliases=["혼다", "Honda"]),
        _brand("포르쉐", aliases=["포르쉐", "Porsche"]),
        _brand("랜드로버", aliases=["랜드로버", "재규어"]),
        _brand("포드", aliases=["포드", "Ford"]),
        _brand("링컨", query="링컨 자동차"),
        _brand("지프"),
        _brand("캐딜락"),
        _brand("폴스타", aliases=["폴스타", "Polestar"]),
        _brand("푸조", aliases=["푸조", "Peugeot"]),
        _brand("마세라티"),
        _brand("람보르기니"),
        _brand("페라리"),
        _brand("벤틀리"),
        _brand("롤스로이스"),
    ],
    # 브랜드 검색 결과 중 자동차와 무관한 기사(야구단·인물 등)를 거르는 단어.
    # 제목·요약에 하나라도 있어야 남긴다.
    "auto_terms": [
        "자동차", "완성차", "차량", "신차", "전기차", "하이브리드", "SUV", "세단", "픽업",
        "모델", "출시", "판매", "수입차", "딜러", "시승", "충전", "배터리", "모빌리티",
        "리콜", "공장", "생산", "주행", "엔진", "트림", "출고",
    ],
    # 외신(구글 뉴스 RSS, 키 필요 없음). queries는 영문 검색어
    "foreign": {
        "enabled": True,
        "hl": "en-US", "gl": "US", "ceid": "US:en",
        "queries": [
            "Hyundai Motor", "Kia Corp", "Genesis Motor", "Korean automakers",
            "Tesla", "BYD", "Toyota", "Volkswagen", "General Motors", "Ford Motor",
            "Stellantis", "Mercedes-Benz", "BMW", "Honda Motor",
            "auto tariffs", "electric vehicle sales",
        ],
    },
    # 발제 후보 이슈의 기사 본문 수집(보도자료성 이슈·외신은 제외)
    "bodies": {"enabled": True, "issues": 10, "per_issue": 2, "max_chars": 6000},
    # 이슈 정렬: latest(최신순) / score(점수순)
    "sort": "latest",
    # 키워드별로 가져올 페이지 수(1페이지=100건)
    "pages_per_keyword": 1,
    # 최근 몇 시간 기사만 볼지
    "lookback_hours": 24,
    # 우리 매체 이름. 이미 보도한 이슈를 '자사 기보도'로 표시한다.
    "my_press": "",
    # 브랜드 외 관심 대상(부품사·배터리사 등). 등장하면 가중치를 준다.
    "watch_terms": ["현대모비스", "현대글로비스", "현대위아", "LG에너지솔루션", "삼성SDI", "SK온"],
    # 보도자료성 판별 단어
    "release_markers": {
        "홍보성": ["프로모션", "할인", "이벤트", "캠페인", "기부", "후원", "봉사", "사회공헌",
                 "수상", "시상", "증정", "혜택", "전시", "체험", "팝업", "기념", "무상점검"],
        "사업 발표": ["출시", "공개", "선보", "투자", "협약", "MOU", "체결", "개최", "오픈",
                  "론칭", "도입", "업무협약"],
    },
    # 보도자료 배포 매체(여기서 나온 기사는 보도자료로 본다)
    "release_press": ["뉴스와이어", "보도자료"],
    # 모든 이슈에 적용하는 '틀어보기' 시각. covered_if 단어가 기사에 있으면 이미 다룬 것으로 본다.
    "generic_twists": [
        {"view": "소비자 입장에서 달라지는 점(가격·혜택·불편)", "covered_if": ["소비자", "고객", "구매자"]},
        {"view": "숫자 다시 보기: 비율·1대당·전년 대비로 환산", "covered_if": ["비중", "대당", "1대당"]},
        {"view": "경쟁 브랜드는 어떻게 하고 있나(비교 기사)", "covered_if": ["경쟁사", "경쟁 모델", "라이벌"]},
    ],
    # 발제 각도 분류. 제목/요약에 단어가 들어가면 해당 각도를 붙인다.
    "angles": {
        "실적": {
            "terms": ["실적", "영업이익", "매출", "순이익", "어닝", "컨센서스"],
            "angle": "실적 해부: 숫자 뒤의 원인(믹스·환율·인센티브) 짚기",
            "checks": ["회사 IR 자료 원문 확보", "전년·전분기 대비 증감 확인", "증권가 전망치 자료 요청"],
            "twists": [
                {"view": "협력사·부품업계로 번지는 영향", "covered_if": ["협력사", "부품사", "부품업계"]},
                {"view": "주가·투자자 시각(시장 기대치 대비)", "covered_if": ["주가", "컨센서스", "증권가", "목표주가"]},
                {"view": "판매 대수 대비 수익성(대당 이익)으로 다시 보기", "covered_if": ["대당", "판매단가", "ASP"]},
            ],
        },
        "판매": {
            "terms": ["판매", "점유율", "판매량", "수출", "내수", "등록"],
            "angle": "판매 데이터 기사: 추이·순위 변화 중심",
            "checks": ["월별 판매 원자료 확보", "브랜드·차종별 세부 수치 확인"],
            "twists": [
                {"view": "차종·연료별로 쪼개 보면 달라지는 흐름", "covered_if": ["차종별", "연료별", "하이브리드"]},
                {"view": "수입차·국산차 점유율 구도 변화", "covered_if": ["점유율"]},
                {"view": "출고 대기·재고 등 현장 상황", "covered_if": ["출고", "대기", "재고"]},
            ],
        },
        "관세·통상": {
            "terms": ["관세", "통상", "무역", "IRA", "보조금", "환율", "FTA"],
            "angle": "거시 변수 영향 분석: 업체별 손익 영향 추정",
            "checks": ["정부·업계 공식 발표 원문 확인", "업체별 영향 규모 자료 요청"],
            "twists": [
                {"view": "중소 협력사·부품업체 부담", "covered_if": ["협력사", "부품"]},
                {"view": "현지 생산 확대와 국내 생산 공백", "covered_if": ["현지 생산", "현지생산", "국내 생산"]},
                {"view": "소비자 가격 전가 여부", "covered_if": ["가격 인상", "가격인상", "소비자 가격"]},
            ],
        },
        "신차": {
            "terms": ["출시", "신차", "공개", "사전계약", "풀체인지", "페이스리프트"],
            "angle": "신차 경쟁력 점검: 가격·사양·경쟁 모델 비교",
            "checks": ["가격표·제원표 확보", "시승 일정 확인"],
            "twists": [
                {"view": "가격 정책: 경쟁 모델·이전 모델 대비", "covered_if": ["만원", "가격"]},
                {"view": "판매 목표의 현실성", "covered_if": ["판매 목표", "목표 판매"]},
                {"view": "브랜드 라인업 속 위치(전동화·세그먼트 공백)", "covered_if": ["라인업"]},
            ],
        },
        "리콜·품질": {
            "terms": ["리콜", "결함", "무상수리", "화재", "급발진", "품질"],
            "angle": "소비자 영향 점검: 대상 차량 규모·조치 내용",
            "checks": ["국토부·제조사 리콜 공지 원문 확인", "대상 대수·차종 확인"],
            "twists": [
                {"view": "같은 부품을 쓴 다른 차종으로 번질 가능성", "covered_if": ["동일 부품", "다른 차종"]},
                {"view": "소비자 보상·수리 대응 실태", "covered_if": ["보상", "수리 기간"]},
                {"view": "반복 리콜 여부(과거 이력과 비교)", "covered_if": ["재발", "반복", "또 리콜"]},
            ],
        },
        "노사": {
            "terms": ["노조", "파업", "임단협", "임금협상", "특근"],
            "angle": "생산 차질 규모 점검",
            "checks": ["노사 양측 입장 확인", "생산 손실 대수 자료 요청"],
            "twists": [
                {"view": "협력사·지역경제 파급", "covered_if": ["협력사", "지역 경제", "지역경제"]},
                {"view": "생산 차질이 출고 대기에 주는 영향", "covered_if": ["출고", "대기"]},
                {"view": "다른 완성차 노사 협상과 비교", "covered_if": ["업계 전반", "다른 완성차"]},
            ],
        },
        "전동화·배터리": {
            "terms": ["전기차", "배터리", "충전", "하이브리드", "수소", "캐즘"],
            "angle": "전동화 전략 흐름: 투자·라인업 변화",
            "checks": ["투자 규모·일정 공식 자료 확인", "판매 비중 수치 확보"],
            "twists": [
                {"view": "수요 둔화 속 투자 속도 조절 여부", "covered_if": ["속도 조절", "연기", "캐즘"]},
                {"view": "충전 인프라·보조금 등 수요 변수", "covered_if": ["충전소", "보조금"]},
                {"view": "배터리사와 완성차 간 힘의 균형", "covered_if": ["공급 계약", "협상력"]},
            ],
        },
        "지배구조·인사": {
            "terms": ["인사", "사장", "부회장", "회장", "지배구조", "지분"],
            "angle": "인사·지배구조 의미 해석",
            "checks": ["공시·보도자료 원문 확인", "인사 배경 취재"],
            "twists": [
                {"view": "인사 뒤 달라질 사업 우선순위", "covered_if": ["우선순위", "전략 변화"]},
                {"view": "세대교체·외부 영입 흐름", "covered_if": ["세대교체", "외부 영입"]},
            ],
        },
    },
    # 출력 위치
    "output_dir": "output",
    # 한번 본 기사 기록(신규/지속 이슈 판별용)
    "history_file": "data/history.json",
    "history_days": 14,
    # AI 발제안 설정. provider: claude / gemini / both
    "ai": {
        "provider": "claude",
        "model": "claude-opus-5-5",
        "effort": "high",
        "gemini_model": "gemini-pro-latest",
        "claude_code_model": "",   # 구독 로그인 때 쓸 모델(비우면 Claude Code 기본값). 예: opus, sonnet
        "max_pitches": 5,
        "max_clusters": 15,
        "style_file": "style/house_style.md",
    },
    # 도메인 → 매체명 추가 매핑(기본 표에 없는 매체)
    "press_map": {},
    # OSINT 데스크(해외 1차 출처 레이더·역추적)
    "osint": {
        "lookback_days": 7,        # 이번 수집에서 볼 기간
        "mosaic_days": 14,         # 모자이크(다른 채널 신호 묶기)에 쓰는 과거 신호 기간
        "domestic_days": 30,       # 국내 기보도 검색 기간
        "max_candidates": 8,
        "translate_max": 150,      # 결과 화면에 한국어로 보여줄 외국어 자료 최대 건수(번역 AI 사용)
        "fetch_docs": True,        # 발제 후보의 1차 출처 원문(정부·기업 사이트) 앞부분을 가져온다
        "auto_minutes": 0,         # 창을 켜두면 N분마다 자동 실행(0=끔)
        "watchlist_file": "watchlist.json",
        "db_file": "data/osint.db",
        "channels": {
            # ── 정부·공공(1차 자료)
            "sec": {"enabled": True, "name": "SEC 공시", "weight": 5,
                    "forms": "8-K,6-K,10-Q,10-K,S-1,S-4,425", "priorities": ["high", "mid"]},
            "courts": {"enabled": True, "name": "미국 법원", "weight": 5, "kinds": ["r", "o"],
                       "entities_per_query": 6, "priorities": ["high", "mid"]},
            "nhtsa": {"enabled": True, "name": "NHTSA 리콜", "weight": 4, "model_years": 4, "refresh_hours": 12,
                      "makes": {"HYUNDAI": "현대자동차", "KIA": "기아", "GENESIS": "제네시스"}},
            "fed_register": {"enabled": True, "name": "미 연방관보", "weight": 4, "priorities": ["high", "mid"],
                             "max_entities": 30, "per_page": 20,
                             # 기업명과 무관하게 볼 정책 주제(반덤핑·관세·안전 규정 등)
                             "topics": ["lithium-ion batteries", "electric vehicle", "passenger vehicle tires",
                                        "automobile parts", "motor vehicle safety standard",
                                        "critical minerals"]},
            "us_federal": {"enabled": True, "name": "미 연방정부 발표", "weight": 4, "sites": [
                "nhtsa.gov", "transportation.gov", "energy.gov", "epa.gov", "commerce.gov", "trade.gov",
                "usitc.gov", "ustr.gov", "treasury.gov", "whitehouse.gov", "ftc.gov", "justice.gov",
                "cbp.gov", "dol.gov"], "sites_per_query": 7},
            "gov_press": {"enabled": True, "name": "주정부·지자체 발표", "weight": 4, "sites": [
                "gov.georgia.gov", "georgia.org", "governor.alabama.gov", "madeinalabama.com", "tn.gov",
                "governor.ky.gov", "ced.ky.gov", "governor.ohio.gov", "michigan.gov", "in.gov", "iedc.in.gov",
                "azgovernor.gov", "gov.louisiana.gov", "opportunitylouisiana.gov", "pa.gov", "nc.gov",
                "sccommerce.com", "gov.texas.gov"]},
            "eu_comp": {"enabled": True, "name": "EU 집행위", "weight": 4, "sites": ["ec.europa.eu"],
                        "extra": "(merger OR antitrust OR competition OR subsidy OR tariff OR investigation)"},
            "china_gov": {"enabled": True, "name": "중국 정부 발표", "weight": 4, "lang": "zh", "sites": [
                "gov.cn", "miit.gov.cn", "mofcom.gov.cn", "ndrc.gov.cn", "samr.gov.cn", "customs.gov.cn"],
                "priorities": ["high", "mid"]},
            "kr_gov": {"enabled": True, "name": "한국 정부 보도자료", "weight": 2, "lang": "ko",
                       # 정책브리핑·부처 사이트를 구글 뉴스로 검색(정책브리핑 RSS 주소는 공개 목록이 자주 바뀐다)
                       "sites": ["korea.kr", "motie.go.kr", "molit.go.kr", "me.go.kr", "moef.go.kr", "ftc.go.kr"],
                       "terms": ["자동차", "전기차", "수소차", "친환경차", "미래차", "자율주행", "모빌리티", "이차전지",
                                 "배터리", "리콜", "자동차 부품", "타이어", "충전", "관세"],
                       "terms_per_query": 7, "feeds": []},
            # ── 기업 발표
            "pr_wire": {"enabled": True, "name": "PR 와이어·파트너사 발표", "weight": 3, "sites": [
                "prnewswire.com", "businesswire.com", "globenewswire.com", "accessnewswire.com",
                "newsfilecorp.com", "hyundainews.com", "kiamedia.com", "news.gm.com", "media.ford.com",
                "stellantis.com"]},
            # ── 언론
            "local_media": {"enabled": True, "name": "현지 지방 매체", "weight": 3, "by_location": True,
                            "priorities": ["high"], "max_queries": 24},
            "trade_media": {"enabled": True, "name": "해외 업계 전문지", "weight": 2, "sites": [
                "autonews.com", "electrive.com", "insideevs.com", "electrek.co", "wardsauto.com",
                "automotivedive.com", "supplychaindive.com", "freightwaves.com", "just-auto.com",
                "batteryindustry.net"]},
            "global_media": {"enabled": True, "name": "해외 주요 언론", "weight": 2, "priorities": ["high"],
                             "max_queries": 6},
            "china_media": {"enabled": True, "name": "중국 매체", "weight": 3, "lang": "zh",
                            "priorities": ["high", "mid"]},
            "feeds": {"enabled": True, "name": "사용자 RSS", "weight": 3, "list": []},
        },
    },
    # API 키(비워두면 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET /
    # ANTHROPIC_API_KEY / GEMINI_API_KEY 사용)
    "naver_client_id": "",
    "naver_client_secret": "",
    "anthropic_api_key": "",
    "gemini_api_key": "",
    # Claude 연결 방식: api(API 키·사용량 과금) / subscription(Claude Code 구독 로그인)
    "claude_auth": "api",
    "courtlistener_token": "",     # CourtListener(미국 법원) API 토큰
    "sec_email": "",               # SEC가 요구하는 접속자 연락처(이메일)
    "telegram_bot_token": "",
    "telegram_chat_id": "",
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
    """기존 config.json에 values를 덮어써 저장한다(GUI 설정 저장용). 하위 항목은 합친다."""
    p = Path(path)
    current = {}
    if p.exists():
        with p.open(encoding="utf-8") as f:
            current = json.load(f)
    current = _merge(current, values)
    with p.open("w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)


def search_queries(config):
    """네이버에 던질 검색어: 주제 키워드 + 브랜드 검색어(중복 제거)."""
    queries = list(config.get("keywords", []))
    if config.get("search_brands", True):
        queries += [b["query"] for b in config.get("brands", [])]
    return list(dict.fromkeys(q for q in queries if q))


def brands_from_names(names, current):
    """GUI에서 고친 브랜드 이름 목록을 설정 형식으로. 기존 항목은 검색어·표기를 유지."""
    by_name = {b["name"]: b for b in current}
    return [by_name.get(n) or _brand(n) for n in names]
