# exe 빌드 안내 (PyInstaller)

평소에는 직접 빌드할 필요가 없다. 코드를 GitHub에 올리면 자동으로 Windows exe를 만들어
[다운로드 페이지](https://github.com/gh98kim-hub/p1/releases/tag/balje-latest)에 올린다
(`.github/workflows/build-exe.yml`). 아래는 내 PC에서 직접 만들 때의 방법이다.

## 1. 준비 (한 번만)

1. **Python 3.12 설치**: python.org에서 Windows 설치 파일을 받는다. 설치 첫 화면에서
   **"Add python.exe to PATH"를 반드시 체크**한다.
2. **소스 받기**: GitHub 저장소에서 `Code → Download ZIP`으로 받아 압축을 푼다(예: `C:\balje`).
3. **명령 창 열기**: 압축을 푼 폴더에서 주소창에 `cmd`를 입력하고 엔터.
4. **가상환경 만들기**(다른 파이썬 프로그램과 섞이지 않게):

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller pytest
```

명령 창 맨 앞에 `(.venv)`가 붙으면 가상환경이 켜진 것이다. 창을 새로 열 때마다
`.venv\Scripts\activate`를 다시 실행한다.

## 2. 빌드 전 확인

```bat
python -m pytest -q
python app.py
```

테스트가 모두 통과하고, `python app.py`로 창이 뜨면 빌드할 준비가 된 것이다.

## 3. 빌드 명령

```bat
pyinstaller --noconfirm Balje.spec
```

1~3분 뒤 `dist\Balje.exe`가 생긴다. 이 파일 하나만 원하는 폴더로 옮겨 더블클릭하면 된다.

다시 빌드할 때 이전 결과가 꼬이면 `build`, `dist` 폴더를 지우고 아래처럼 실행한다.

```bat
pyinstaller --noconfirm --clean Balje.spec
```

## 4. `Balje.spec` 설명

`.spec`은 PyInstaller에게 "무엇을, 어떻게 묶을지" 알려주는 파이썬 형식의 설정 파일이다.

```python
a = Analysis(
    ["app.py"],                 # 시작 파일. 여기서 import하는 모듈을 따라가며 모두 묶는다
    pathex=["."],               # 모듈을 찾을 폴더(저장소 루트)
    datas=[                     # 코드가 아닌 파일. (원본 경로, exe 안의 폴더)
        ("style/house_style.md", "style"),
        ("samples", "samples"),
        ("osint/default_watchlist.json", "osint"),
    ],
    hiddenimports=[...],        # 함수 안에서 늦게 import해서 자동으로 못 찾는 모듈
    excludes=[...],             # 쓰지 않는 큰 라이브러리(용량 줄이기)
)
pyz = PYZ(a.pure)               # 파이썬 코드 묶음
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name="Balje",         # 결과 파일 이름 → dist\Balje.exe
          console=False,        # 검은 콘솔 창 없이 창만 띄움(오류를 보려면 True로 바꿔 빌드)
          upx=False)            # UPX 압축 끔(백신 오탐이 늘어남)
```

### 자주 고치는 부분

| 하고 싶은 것 | 고칠 곳 |
|---|---|
| exe 이름 바꾸기 | `name="Balje"` → 원하는 이름(영문 권장) |
| 아이콘 넣기 | `EXE(...)` 안에 `icon="balje.ico"` 추가(.ico 파일을 저장소 루트에) |
| 오류 메시지를 콘솔로 보기 | `console=True`로 바꿔 빌드 → 실행하면 검은 창에 오류가 나온다 |
| 파일 더 넣기 | `datas`에 `("경로", "exe 안 폴더")` 추가. 코드에서는 `gui.resource("폴더/파일")`로 읽는다 |
| "No module named ..." 오류 | 그 모듈 이름을 `hiddenimports`에 추가 |

### 데이터 파일은 어디에 풀리나

exe는 실행할 때 임시 폴더(`sys._MEIPASS`)에 묶인 파일을 푼다. 프로그램은 두 곳을 구분해 쓴다.

- **묶인 기본 파일**(샘플, 기본 추적 대상 목록, 기본 문체): 임시 폴더에서 읽기만 한다.
- **기자가 고치는 파일**(`config.json`, `watchlist.json`, `style/`, `output/`, `data/`):
  exe가 있는 폴더에 만든다. 처음 실행 때 기본 파일을 복사해 두므로, exe를 새 버전으로 바꿔도 설정은 그대로 남는다.

## 5. 문제 해결

| 증상 | 해결 |
|---|---|
| "Windows의 PC 보호" 창 | **추가 정보 → 실행**. 서명되지 않은 개인 프로그램이라 뜨는 경고다 |
| 백신이 exe를 지움 | 백신 예외에 exe 폴더를 추가하거나, 회사 보안팀에 허용 요청 |
| 실행하면 바로 꺼짐 | `console=True`로 다시 빌드해 오류 메시지 확인 |
| exe가 30MB 안팎 | 정상. 파이썬과 Claude·Gemini 라이브러리가 함께 들어 있다 |
| 빌드는 되는데 창 글자가 깨짐 | Windows에 '맑은 고딕'이 없는 경우. 코드의 `FONT`를 다른 한글 글꼴로 바꾼다 |

## 6. 자체 점검

exe가 제대로 묶였는지 확인하는 숨은 옵션이 있다(자동 빌드에서도 쓴다).

```bat
Balje.exe --selftest 결과.txt
```

`결과.txt`에 `gui ok`, `pipeline ok`, `osint watchlist ok`가 나오면 정상이다.
