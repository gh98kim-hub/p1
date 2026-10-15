# -*- mode: python ; coding: utf-8 -*-
# 발제 도우미 + OSINT 데스크 Windows exe 빌드 설정.
# 사용: pyinstaller --noconfirm Balje.spec   → dist/Balje.exe

a = Analysis(
    ["app.py"],
    pathex=["."],
    # (원본 경로, exe 안의 폴더). 실행 중에는 sys._MEIPASS 아래에 풀린다.
    datas=[
        ("style/house_style.md", "style"),
        ("samples", "samples"),
        ("osint/default_watchlist.json", "osint"),
    ],
    # 지연 import(함수 안에서 불러오는 모듈)도 확실히 넣는다.
    hiddenimports=[
        "osint.radar", "osint.reverse", "osint.notify",
        "osint.sources.sec_edgar", "osint.sources.courts", "osint.sources.nhtsa", "osint.sources.news",
        "osint.sources.federal_register", "osint.board", "osint.classify", "balje.board", "balje.dashboard", "balje.watch_editor",
    ],
    excludes=["matplotlib", "numpy", "pandas", "PyQt5", "PySide6", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Balje",
    console=False,       # 창 프로그램(검은 콘솔 창 없음)
    upx=False,           # UPX 압축은 백신 오탐을 늘려 끈다
    debug=False,
    strip=False,
)
