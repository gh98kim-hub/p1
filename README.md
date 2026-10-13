# 발제 도우미 (balje)

자동차 담당 기자의 아침 발제를 돕는 프로그램이다.
뉴스를 모아 같은 이슈끼리 묶고, 점수를 매기고, 이슈마다 발제 각도와 취재 체크리스트를 붙인다.
원하면 Claude나 Gemini(또는 둘 다)로 발제안 초안도 쓴다.

발제 노트에 들어가는 것:

- **이슈 순위**: 기사 수·매체 수·브랜드·타사 단독·최근성·수치·신규 여부로 점수화
- **보도자료 점검**: 보도자료로 보이는 이슈(홍보성/사업 발표)마다 발제 가치 판단(앵글 검토 가치 있음·묶음 기획 소재·단신·생략)과 살릴 앵글
- **묶어보기**: 서로 다른 브랜드의 같은 유형 이슈(할인·캠페인, 신차 등)를 묶은 업계 흐름 기획 후보
- **틀어보기**: 이미 나온 기사에 아직 안 보이는 시각(협력사 영향, 소비자 가격, 대당 수익성 등)
- **브랜드별 기사량**: 국내외 브랜드 30개별 기사·이슈 수
- **AI 발제안**: 발제안 + 보도자료 점검 + 틀어보기를 AI가 자료 근거로 정리(Claude·Gemini 비교 가능)

```
수집(네이버 API 또는 모니터링 결과 파일)
  → 중복 제거 · 최근 N시간 필터
  → 이슈 묶기(제목 유사도)
  → 점수화(기사 수 · 매체 수 · 관심 대상 · 타사 단독 · 최근성 · 수치 · 신규 여부)
  → 규칙 기반 발제 메모(각도 · 체크리스트 · 근거 기사)
  → (선택) Claude 발제안 초안
  → 발제노트_YYYYMMDD_HHMM.md / .html
```

## 프로그램(exe)으로 쓰기 — Windows

1. [다운로드 페이지](https://github.com/gh98kim-hub/p1/releases/tag/balje-latest)에서 `Balje.exe`를 내려받는다.
2. 바탕화면 등에 `발제도우미` 폴더를 하나 만들고 그 안에 둔다. 설정(`config.json`)과 결과(`output/`)가 이 폴더에 생긴다.
3. 더블클릭해 실행한다.
   - 처음 실행 때 "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누른다(서명되지 않은 개인 프로그램이라 뜨는 경고).
4. **[샘플로 시험]**으로 키 없이 먼저 확인한다.
5. **[설정]**에 네이버 API 키(필요하면 Claude API 키, 우리 매체 이름)를 넣고 **[발제 노트 만들기]**를 누른다.
   끝나면 브라우저로 발제 노트가 열린다.

창에서 할 수 있는 일: 네이버 검색어·시간 범위 지정, 브랜드 전체 검색 켜고 끄기, 모니터링 결과 파일 불러오기,
자료 폴더 지정, AI 선택(사용 안 함 / Claude / Gemini / 둘 다 비교).
[설정]에서 API 키, Gemini 모델, 검색 브랜드 목록을 고친다.

## 설치(직접 실행할 때)

Python 3.10 이상이면 된다. 기본 기능은 표준 라이브러리만 쓴다.

```bash
pip install -r requirements.txt   # AI 발제안(--ai)을 쓸 때만 필요
cp config.example.json config.json  # 검색어·관심 대상·자사 매체명 수정
```

## 사용법

창으로 쓰려면 `python app.py`. 아래는 명령줄 사용법이다.

### 1) 네이버 뉴스 API로 바로 수집

[네이버 개발자센터](https://developers.naver.com)에서 '검색' API 애플리케이션을 등록해 키를 받는다.

```bash
export NAVER_CLIENT_ID=발급받은_ID
export NAVER_CLIENT_SECRET=발급받은_SECRET
python -m balje                          # config.json의 검색어로 수집
python -m balje --keywords "현대차,기아,관세" --hours 12
```

Windows(PowerShell)는 `$env:NAVER_CLIENT_ID="..."` 식으로 설정한다.

### 2) 기존 네이버 뉴스 모니터링 프로그램과 연결

모니터링 프로그램이 저장한 JSON/CSV를 그대로 넣으면 된다. 네이버 수집은 건너뛴다.

```bash
python -m balje --input 모니터링결과.json
python -m balje --input 오전.csv --input 오후.csv
```

필드명은 아래 중 아무거나 쓰면 알아서 읽는다.

| 항목 | 인식하는 필드명 |
|---|---|
| 제목(필수) | `title`, `제목`, `headline` |
| 링크 | `originallink`, `link`, `url`, `링크`, `주소` |
| 요약 | `description`, `summary`, `요약`, `본문`, `content` |
| 매체 | `press`, `source`, `언론사`, `매체` (없으면 링크 도메인으로 추정) |
| 일시 | `pubDate`, `published`, `date`, `날짜`, `일시` |

네이버 API 응답(`{"items": [...]}`)을 그대로 저장한 파일도 읽는다.

### 3) 내 자료 넣기

보도자료·취재 메모를 `.txt`/`.md`로 한 폴더에 넣고 지정한다. AI 발제안이 이 자료를 근거로 쓴다.

```bash
python -m balje --materials 오늘자료 --ai
```

### 4) AI 발제안 (Claude · Gemini)

```bash
export ANTHROPIC_API_KEY=발급받은_키   # Claude
export GEMINI_API_KEY=발급받은_키      # Gemini (Google AI Studio에서 발급)
python -m balje --ai claude
python -m balje --ai gemini
python -m balje --ai both              # 둘 다 써서 나란히 비교
```

- Gemini 모델 기본값은 `gemini-pro-latest`(최신 Pro를 가리키는 별칭). 빠르고 저렴한 쪽은 `gemini-3.8-flash`.
  설정의 `ai.gemini_model`이나 창의 [설정]에서 바꾼다.

- 수집 기사와 기자 제공 자료**만** 근거로 쓰도록 지시한다. 자료에 없는 내용은 '추가 확인 필요'로 돌린다.
- 모든 문장에 근거 번호(`[A003]` 기사, `[M1]` 기자 자료)를 달게 해 바로 대조할 수 있다.
- 문체는 `style/house_style.md`를 따른다. 부장 스타일 발제 예시를 이 파일 아래에 붙여 넣으면 그 톤을 따라간다.
- 초안일 뿐이다. 반드시 근거 기사와 대조한 뒤 쓴다.

## 주요 옵션

| 옵션 | 설명 |
|---|---|
| `--input 파일` | 기사 파일(JSON/CSV). 여러 번 지정 가능 |
| `--keywords "a,b"` | 검색어 덮어쓰기 |
| `--hours N` | 최근 N시간 기사만(0이면 전체) |
| `--materials 폴더` | 기자 제공 자료 폴더 |
| `--ai [claude\|gemini\|both]` | AI 발제안 초안 작성(값 생략 시 설정 따름) |
| `--no-brands` | 브랜드 검색어를 쓰지 않음 |
| `--top N` | 상세 표시할 이슈 수(기본 10) |
| `--out 폴더` | 출력 폴더(기본 `output/`) |
| `--save-raw` | 수집 기사 원본 JSON 저장(모니터링 기록용) |
| `--no-history` | 신규/지속 이슈 판별 기록을 쓰지 않음 |

## 설정(config.json)

- `keywords`: 네이버 검색어(주제)
- `search_brands` / `brands`: 브랜드 검색 여부와 목록(검색어 `query`, 기사 속 표기 `aliases`)
- `auto_terms`: 브랜드 검색 결과에서 자동차와 무관한 기사(야구단·인물 등)를 거르는 단어
- `release_markers` / `release_press`: 보도자료성 판별 단어와 보도자료 배포 매체
- `generic_twists`, `angles.*.twists`: '틀어보기' 시각 목록(`covered_if` 단어가 기사에 있으면 '이미 다룸')
- `lookback_hours`: 기본 조회 시간 범위
- `my_press`: 우리 매체 이름. 이미 쓴 이슈에 '자사 기보도' 표시
- `watch_terms`: 출입처·관심 기업. 등장하면 점수 가산
- `angles`: 발제 각도 분류표(단어 → 각도 문구 · 체크리스트). 출입처 사정에 맞게 고쳐 쓴다
- `press_map`: 도메인 → 매체명 추가 매핑

## 신규/지속 이슈

실행할 때마다 본 기사 링크를 `data/history.json`에 남긴다(기본 14일 보관).
다음 실행에서 기사 절반 이상이 이미 본 링크면 '지속' 이슈로 표시하고, 처음 보는 이슈에 가산점을 준다.

## 샘플로 시험해보기

`samples/`의 기사와 자료는 **가상 예시**다(실제 기업·사실과 무관).

```bash
python -m balje --config samples/sample_config.json --input samples/sample_articles.json \
  --hours 0 --no-history --materials samples/materials
```

## 테스트

```bash
pip install pytest
python -m pytest -q
```
