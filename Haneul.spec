# -*- mode: python ; coding: utf-8 -*-
# 김하늘 전용 편집툴 Windows exe 빌드 설정.
# 사용: pyinstaller --noconfirm Haneul.spec   → dist/Haneul.exe

a = Analysis(
    ["haneul_app.py"],
    pathex=["."],
    # 화면(HTML)과 브라우저용 연결 스크립트. 실행 중에는 sys._MEIPASS/haneul/web 아래에 풀린다.
    datas=[
        ("haneul/web/index.html", "haneul/web"),
        ("haneul/web/shim.js", "haneul/web"),
    ],
    hiddenimports=["anthropic"],
    excludes=["matplotlib", "numpy", "pandas", "PyQt5", "PySide6", "IPython", "google", "osint"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Haneul",
    console=False,       # 창 프로그램(검은 콘솔 창 없음)
    upx=False,           # UPX 압축은 백신 오탐을 늘려 끈다
    debug=False,
    strip=False,
)
