"""더블클릭으로 쓰는 창(GUI). exe로 묶을 때의 진입점이기도 하다."""

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import pipeline
from .config import load_config, save_config

FONT = ("Malgun Gothic", 10)


def app_dir():
    """설정·결과 파일을 둘 폴더. exe면 exe가 있는 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def resource(rel):
    """exe 안에 함께 묶인 파일(샘플·문체 파일) 경로."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def prepare_workdir():
    os.chdir(app_dir())
    style = Path("style/house_style.md")
    if not style.exists() and resource("style/house_style.md").exists():
        style.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(resource("style/house_style.md"), style)


def open_path(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - 로컬 결과 폴더 열기
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class SettingsDialog(tk.Toplevel):
    FIELDS = [
        ("naver_client_id", "네이버 Client ID", False),
        ("naver_client_secret", "네이버 Client Secret", True),
        ("anthropic_api_key", "Claude API 키 (AI 발제안용)", True),
        ("my_press", "우리 매체 이름", False),
    ]

    def __init__(self, master, config):
        super().__init__(master)
        self.title("설정")
        self.resizable(False, False)
        self.transient(master)
        self.vars = {}
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        for row, (key, label, secret) in enumerate(self.FIELDS):
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=config.get(key, ""))
            ttk.Entry(frm, textvariable=var, width=42, show="•" if secret else "").grid(
                row=row, column=1, sticky="we", padx=(8, 0), pady=4)
            self.vars[key] = var
        ttk.Label(frm, foreground="#666",
                  text="키는 이 프로그램 폴더의 config.json에 저장됩니다. 다른 사람과 파일을 공유할 때 주의하세요.").grid(
            row=len(self.FIELDS), column=0, columnspan=2, sticky="w", pady=(8, 0))
        btns = ttk.Frame(frm)
        btns.grid(row=len(self.FIELDS) + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="저장", command=self.save).pack(side="right", padx=6)
        self.saved = None
        self.grab_set()

    def save(self):
        self.saved = {k: v.get().strip() for k, v in self.vars.items()}
        save_config(self.saved)
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("발제 도우미")
        self.option_add("*Font", FONT)
        ttk.Style(self).configure(".", font=FONT)
        self.minsize(640, 520)
        self.config_data = load_config()
        self.log_queue = queue.Queue()
        self.worker = None
        self.last_html = None
        self.input_files = []
        self.materials_dir = None
        self._build()
        self.after(100, self._drain_log)
        if not (self.config_data.get("naver_client_id") or os.environ.get("NAVER_CLIENT_ID")):
            self.log("처음이면 [설정]에서 네이버 API 키를 넣으세요. 키 없이 [샘플로 시험]도 해볼 수 있습니다.\n")

    # ------------------------------------------------------------ 화면 구성
    def _build(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        src = ttk.LabelFrame(root, text="기사 가져오기", padding=10)
        src.pack(fill="x")
        self.source = tk.StringVar(value="naver")
        ttk.Radiobutton(src, text="네이버에서 검색", value="naver", variable=self.source).grid(row=0, column=0, sticky="w")
        ttk.Label(src, text="검색어(쉼표로 구분)").grid(row=0, column=1, sticky="e", padx=(12, 4))
        self.keywords = tk.StringVar(value=", ".join(self.config_data["keywords"]))
        ttk.Entry(src, textvariable=self.keywords, width=36).grid(row=0, column=2, sticky="we")
        ttk.Label(src, text="최근").grid(row=1, column=1, sticky="e", padx=(12, 4), pady=(6, 0))
        hrs = ttk.Frame(src)
        hrs.grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.hours = tk.StringVar(value=str(self.config_data["lookback_hours"]))
        ttk.Spinbox(hrs, from_=1, to=168, textvariable=self.hours, width=5).pack(side="left")
        ttk.Label(hrs, text="시간 기사").pack(side="left", padx=4)

        ttk.Radiobutton(src, text="파일에서 불러오기", value="file", variable=self.source).grid(
            row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Button(src, text="파일 선택…", command=self.pick_files).grid(row=2, column=1, sticky="e", pady=(10, 0))
        self.files_label = ttk.Label(src, text="(모니터링 결과 JSON/CSV)", foreground="#666")
        self.files_label.grid(row=2, column=2, sticky="w", padx=4, pady=(10, 0))
        src.columnconfigure(2, weight=1)

        extra = ttk.LabelFrame(root, text="추가 자료 · AI", padding=10)
        extra.pack(fill="x", pady=(10, 0))
        ttk.Button(extra, text="자료 폴더 선택…", command=self.pick_materials).grid(row=0, column=0, sticky="w")
        self.mat_label = ttk.Label(extra, text="(보도자료·메모 .txt/.md, 선택)", foreground="#666")
        self.mat_label.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(extra, text="지우기", command=self.clear_materials).grid(row=0, column=2, sticky="e")
        self.use_ai = tk.BooleanVar(value=False)
        ttk.Checkbutton(extra, text="Claude로 AI 발제안 초안도 쓰기 (Claude API 키 필요)",
                        variable=self.use_ai).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        extra.columnconfigure(1, weight=1)

        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="설정", command=self.open_settings).pack(side="left")
        ttk.Button(bar, text="샘플로 시험", command=self.run_sample).pack(side="left", padx=6)
        ttk.Button(bar, text="결과 폴더 열기", command=self.open_output).pack(side="left")
        self.run_btn = ttk.Button(bar, text="발제 노트 만들기", command=self.run_main)
        self.run_btn.pack(side="right")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)  # 실행 중에만 표시

        self.log_box = tk.Text(root, height=14, wrap="word", font=FONT, state="disabled",
                               relief="solid", borderwidth=1)
        self.log_box.pack(fill="both", expand=True, pady=(12, 0))

    # ------------------------------------------------------------ 동작
    def log(self, msg):
        self.log_queue.put(str(msg))

    def _drain_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def pick_files(self):
        files = filedialog.askopenfilenames(
            title="기사 파일 선택", filetypes=[("기사 파일", "*.json *.csv"), ("모든 파일", "*.*")])
        if files:
            self.input_files = list(files)
            self.files_label.configure(text=", ".join(Path(f).name for f in files))
            self.source.set("file")

    def pick_materials(self):
        d = filedialog.askdirectory(title="자료 폴더 선택")
        if d:
            self.materials_dir = d
            self.mat_label.configure(text=d)

    def clear_materials(self):
        self.materials_dir = None
        self.mat_label.configure(text="(보도자료·메모 .txt/.md, 선택)")

    def open_settings(self):
        dlg = SettingsDialog(self, self.config_data)
        self.wait_window(dlg)
        if dlg.saved:
            self.config_data.update(dlg.saved)
            self.log("설정을 저장했습니다.")

    def open_output(self):
        out = Path(self.config_data["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        open_path(out.resolve())

    def run_main(self):
        keywords = [k.strip() for k in self.keywords.get().split(",") if k.strip()]
        try:
            hours = float(self.hours.get())
        except ValueError:
            messagebox.showwarning("발제 도우미", "시간은 숫자로 넣으세요.")
            return
        if self.source.get() == "file" and not self.input_files:
            messagebox.showwarning("발제 도우미", "불러올 기사 파일을 선택하세요.")
            return
        if self.source.get() == "naver" and not keywords:
            messagebox.showwarning("발제 도우미", "검색어를 넣으세요.")
            return
        if hours.is_integer():
            hours = int(hours)
        save_config({"keywords": keywords, "lookback_hours": hours})
        self.config_data.update({"keywords": keywords, "lookback_hours": hours})
        inputs = self.input_files if self.source.get() == "file" else []
        self._start(dict(inputs=inputs, materials_dir=self.materials_dir, hours=hours,
                         use_ai=self.use_ai.get()))

    def run_sample(self):
        self._start(dict(inputs=[resource("samples/sample_articles.json")],
                         materials_dir=resource("samples/materials"), hours=0,
                         use_ai=self.use_ai.get(), use_history=False))

    def _start(self, kwargs):
        if self.worker and self.worker.is_alive():
            return
        self.run_btn.configure(state="disabled")
        self.progress.pack(side="right", padx=8)
        self.progress.start(12)
        self.log("─" * 30)

        def work():
            try:
                result = pipeline.run(dict(self.config_data), log=self.log, **kwargs)
                self.after(0, self._done, result["html"], None)
            except pipeline.BaljeError as e:
                self.after(0, self._done, None, str(e))
            except Exception:  # 예상 못 한 오류도 창에 보여준다
                self.after(0, self._done, None, traceback.format_exc())

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _done(self, html_path, error):
        self.progress.stop()
        self.progress.pack_forget()
        self.run_btn.configure(state="normal")
        if error:
            self.log("오류: " + error)
            messagebox.showerror("발제 도우미", error.splitlines()[-1] if error else "오류")
            return
        self.last_html = html_path
        self.log("완료. 브라우저로 발제 노트를 엽니다.")
        webbrowser.open(Path(html_path).resolve().as_uri())


def selftest(result_file):
    """빌드 확인용: 창 생성 + 샘플 실행 + anthropic 로드."""
    lines = []
    try:
        prepare_workdir()
        app = App()
        app.update()
        app.destroy()
        lines.append("gui ok")
        import anthropic  # noqa: F401 - exe에 포함됐는지 확인
        lines.append("anthropic ok")
        r = pipeline.run(load_config(), inputs=[resource("samples/sample_articles.json")],
                         materials_dir=resource("samples/materials"), hours=0,
                         use_history=False, out_dir="selftest_out", log=lambda m: None)
        lines.append(f"pipeline ok {len(r['clusters'])}")
        if os.environ.get("BALJE_SELFTEST_NET") == "1":
            lines += _net_checks()
        code = 0
    except Exception:
        lines.append(traceback.format_exc())
        code = 1
    Path(result_file).write_text("\n".join(lines), encoding="utf-8")
    return code


def _net_checks():
    """가짜 키로 호출해 '인증 실패'가 오면 HTTPS 연결(인증서 포함)은 정상."""
    import urllib.error

    import anthropic

    from .collect import fetch_naver

    try:
        fetch_naver("테스트", client_id="x", client_secret="x")
        raise RuntimeError("naver: 가짜 키로 성공할 수 없음")
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403):
            raise
    try:
        anthropic.Anthropic(api_key="sk-ant-selftest").models.list()
        raise RuntimeError("anthropic: 가짜 키로 성공할 수 없음")
    except anthropic.AuthenticationError:
        pass
    return ["naver https ok", "anthropic https ok"]


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    prepare_workdir()
    App().mainloop()


if __name__ == "__main__":
    main()
