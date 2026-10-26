# 김하늘 전용 편집툴 (exe판)

피플면 제목 작업대의 Windows 실행 파일판이다. 사용법은 사용 설명서(Claude 문서)를 본다.
여기에는 구조와 빌드만 적는다.

- 다운로드: [haneul-latest 릴리스](https://github.com/gh98kim-hub/p1/releases/tag/haneul-latest)
- 웹판: claude.ai 아티팩트 `YCC5CW2KFqRUVs8F1znABy`

## 구조

| 파일 | 하는 일 |
|---|---|
| `haneul/web/index.html` | 화면. 웹판(아티팩트)과 같은 파일이다. 고칠 때는 둘을 같이 바꾼다 |
| `haneul/web/shim.js` | 브라우저에서 `window.claude`(sample·db·user·downloads)를 흉내 내 로컬 서버로 넘긴다 |
| `haneul/server.py` | `127.0.0.1`에서만 여는 웹서버. 화면 조립, `/api/sample`(Claude), `/api/db/*`(자료) |
| `haneul/store.py` | `haneul_data.json` 저장소. 0.5초 모아서 파일에 쓴다 |
| `haneul/config.py` | 설정 파일 읽기, 서버 시작(포트 47321, 쓰이고 있으면 빈 번호) |
| `haneul/gui.py` | exe를 켜면 뜨는 작은 창(Claude 연결 설정·편집툴 열기). `--selftest` |

Claude 호출은 `balje/llm.py`의 `call_claude`를 그대로 쓴다(구독 로그인 또는 API 키).
기본 effort는 `medium`(`haneul_config.json`의 `ai.effort`로 바꾼다).

로컬 서버 보호: `Host`가 `127.0.0.1`·`localhost`인 요청만 받고, POST에는 `X-Haneul: 1` 헤더가 있어야 한다
(다른 웹사이트의 스크립트가 자료를 지우거나 Claude를 부르지 못하게).

## 빌드

`claude/funny-allen-3dl12x` 브랜치에 `haneul/**` 등이 바뀌어 올라가면
`.github/workflows/build-haneul-exe.yml`이 테스트 → exe 빌드 → 자체 점검 → 릴리스 업로드까지 한다.
내 PC에서 직접 만들 때는 `docs/BUILD.md`의 준비 과정을 따른 뒤:

```bat
python -m pytest -q tests/test_haneul.py
python haneul_app.py
pyinstaller --noconfirm Haneul.spec
```

## 웹판 ↔ exe판 자료 옮기기

‘학습 자료 → 내보내기’가 `haneul_export_YYYYMMDD.json`(`format: "haneul-export"`)을 만든다.
`examples`(제목·부제·유형·날짜·본문)와 `config`(스타일 가이드·편집 규칙·칸 설정)가 들어 있다.
양쪽 모두 ‘자료 넣기 → 파일’로 이 파일이나 exe의 `haneul_data.json`을 읽는다. 같은 제목·날짜는 건너뛰고,
`config`가 있으면 그것으로 바꿀지 고르게 한다(지금 스타일 가이드가 비어 있으면 기본으로 체크).
