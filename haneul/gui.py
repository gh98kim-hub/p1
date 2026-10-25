"""exe를 더블클릭하면 뜨는 작은 창. 편집툴 서버를 켜고, Claude 연결을 설정한다.
편집툴 화면은 기본 브라우저에서 열린다. 이 창을 닫으면 편집툴도 꺼진다."""

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from balje import llm

from .config import CONFIG_NAME, DATA_NAME, TITLE, app_dir, load_config, start_app
from .server import build_page

FONT = ("Malgun Gothic", 10)

INSTALL_HELP = """구독(Pro·Max)으로 쓰려면 Anthropic의 공식 프로그램 'Claude Code'가 필요합니다.
(발제 도우미에서 이미 설치·로그인했다면 그대로 씁니다.)

1) 설치: 시작 메뉴에서 'PowerShell'을 열고 아래 한 줄을 붙여 넣고 엔터
   irm https://claude.ai/install.ps1 | iex

2) 설치가 끝나면 이 프로그램을 껐다 켭니다.
3) [Claude 로그인]을 눌러 브라우저에서 Claude 계정으로 로그인합니다."""


class Window(tk.Tk):
    def __init__(self):
        super().__init__()
        self.folder = app_dir()
        self.cfg_path = self.folder / CONFIG_NAME
        self.cfg = load_config(self.cfg_path)
        self.app = start_app(self.folder)
        self.title(TITLE)
        self.geometry("520x440")
        self.minsize(480, 400)
        self.option_add("*Font", FONT)
        self.protocol("WM_DELETE_WINDOW", self.quit_all)
        self._build()
        self.refresh_status()
        self.after(400, self.open_browser)

    def _build(self):
        pad = {"padx": 16, "pady": 6}
        tk.Label(self, text=TITLE, font=("Malgun Gothic", 15, "bold")).pack(anchor="w", padx=16, pady=(16, 0))
        tk.Label(self, text=f"켜져 있습니다 · {self.app.url}", fg="#0D5D6E").pack(anchor="w", **pad)
        row = tk.Frame(self)
        row.pack(fill="x", **pad)
        ttk.Button(row, text="편집툴 열기", command=self.open_browser).pack(side="left")
        ttk.Button(row, text="자료 폴더 열기", command=self.open_folder).pack(side="left", padx=8)

        box = ttk.LabelFrame(self, text="Claude 연결")
        box.pack(fill="x", padx=16, pady=10)
        self.mode = tk.StringVar(value=self.cfg.get("claude_auth") or "subscription")
        ttk.Radiobutton(box, text="구독 로그인 (Claude Pro·Max, Claude Code 필요)", value="subscription",
                        variable=self.mode, command=self.save).pack(anchor="w", padx=10, pady=(8, 2))
        ttk.Radiobutton(box, text="API 키 (사용량만큼 따로 요금)", value="api",
                        variable=self.mode, command=self.save).pack(anchor="w", padx=10)
        krow = tk.Frame(box)
        krow.pack(fill="x", padx=10, pady=6)
        tk.Label(krow, text="API 키").pack(side="left")
        self.key = tk.StringVar(value=self.cfg.get("anthropic_api_key", ""))
        ttk.Entry(krow, textvariable=self.key, show="•").pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(krow, text="저장", command=self.save).pack(side="left")
        brow = tk.Frame(box)
        brow.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Button(brow, text="Claude 로그인", command=self.login).pack(side="left")
        ttk.Button(brow, text="설치 안내", command=lambda: messagebox.showinfo("Claude Code 설치", INSTALL_HELP)).pack(side="left", padx=6)
        ttk.Button(brow, text="상태 다시 확인", command=self.refresh_status).pack(side="left")
        self.status = tk.Label(box, text="확인 중…", fg="#59626B", justify="left", wraplength=460)
        self.status.pack(anchor="w", padx=10, pady=(0, 10))

        tk.Label(self, text="이 창을 닫으면 편집툴도 꺼집니다. 자료는 이 exe가 있는 폴더의 haneul_data.json에 저장됩니다.",
                 fg="#59626B", justify="left", wraplength=480).pack(anchor="w", padx=16, pady=(4, 12))

    def save(self):
        self.cfg["claude_auth"] = self.mode.get()
        self.cfg["anthropic_api_key"] = self.key.get().strip()
        try:
            self.cfg_path.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            messagebox.showerror("저장 실패", f"설정 파일을 쓰지 못했습니다.\n{e}")
            return
        self.refresh_status()

    def refresh_status(self):
        self.status.config(text="확인 중…")

        def work():
            if self.mode.get() == "api":
                ok = bool(self.key.get().strip() or os.environ.get("ANTHROPIC_API_KEY"))
                msg = "API 키로 씁니다." if ok else "API 키를 넣고 [저장]을 누르세요."
            else:
                installed, logged_in, msg = llm.claude_code_status()
                if not installed:
                    msg += " [설치 안내]를 보세요."
                elif not logged_in:
                    msg += " [Claude 로그인]을 누르세요."
            self.after(0, lambda: self.status.config(text=msg))

        threading.Thread(target=work, daemon=True).start()

    def login(self):
        if not llm.open_login_window():
            messagebox.showinfo("Claude Code 설치", INSTALL_HELP)
            return
        messagebox.showinfo("Claude 로그인", "새로 뜬 창의 안내를 따라 로그인한 뒤 [상태 다시 확인]을 누르세요.")

    def open_browser(self):
        webbrowser.open(self.app.url)

    def open_folder(self):
        if sys.platform.startswith("win"):
            os.startfile(self.folder)  # noqa: S606 - 내 폴더를 탐색기로 연다
        else:
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(self.folder)])

    def quit_all(self):
        try:
            self.app.stop()
        finally:
            self.destroy()


def selftest(result_file):
    """exe 자체 점검: 화면 조립, 자료 저장·목록, 다른 사이트 요청 차단, 창 생성. Claude는 부르지 않는다."""
    import tempfile
    import urllib.request
    from urllib.error import HTTPError

    lines, code = [], 0

    def check(name, fn):
        nonlocal code
        try:
            fn()
            lines.append(f"OK   {name}")
        except Exception as e:  # noqa: BLE001
            code = 1
            lines.append(f"FAIL {name}: {type(e).__name__}: {e}")

    def post(url, path, body, header=True):
        req = urllib.request.Request(url + path.lstrip("/"), data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-Haneul": "1"} if header else {})})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    with tempfile.TemporaryDirectory() as d:
        app = start_app(d)
        url = app.url

        def page():
            html = build_page()
            assert TITLE in html and "window.claude" in html, "화면 조립 실패"
            with urllib.request.urlopen(url, timeout=10) as r:
                assert TITLE in r.read().decode("utf-8")

        def db():
            post(url, "/api/db/set", {"path": "examples/a1", "data": {"title": "가\n나", "addedAt": 2}})
            post(url, "/api/db/set", {"path": "examples/a2", "data": {"title": "다", "addedAt": 5}})
            docs = post(url, "/api/db/list", {"collection": "examples", "orderBy": "addedAt", "dir": "desc", "limit": 1000})["docs"]
            assert [x["id"] for x in docs] == ["a2", "a1"], docs
            post(url, "/api/db/delete", {"path": "examples/a2"})
            app.store.flush()
            saved = json.loads((Path(d) / DATA_NAME).read_text(encoding="utf-8"))
            assert list(saved["collections"]["examples"]) == ["a1"], saved

        def blocked():
            try:
                post(url, "/api/db/delete", {"path": "examples/a1"}, header=False)
            except HTTPError as e:
                assert e.code == 403
                return
            raise AssertionError("헤더 없는 요청이 통과했습니다")

        def window():
            w = tk.Tk()
            w.withdraw()
            w.update()
            w.destroy()

        check("화면 조립·열기", page)
        check("자료 저장·목록·삭제", db)
        check("다른 사이트 요청 차단", blocked)
        check("창 만들기", window)
        app.stop()

    Path(result_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    Window().mainloop()
