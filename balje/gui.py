"""더블클릭으로 쓰는 창(GUI). exe로 묶을 때의 진입점이기도 하다."""

import os
import json
import queue
import re
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
from .config import _merge, brands_from_names, load_config, save_config

FONT = ("Malgun Gothic", 10)
SORT_CHOICES = {"최신순": "latest", "점수순": "score"}
SORT_CHOICES_REV = {v: k for k, v in SORT_CHOICES.items()}
AI_CHOICES = [("사용 안 함", None), ("Claude", "claude"), ("Gemini", "gemini"), ("Claude + Gemini 비교", "both")]


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


def open_text(path):
    """마크다운 파일 열기. 연결된 프로그램이 없으면 메모장으로."""
    if sys.platform.startswith("win"):
        try:
            os.startfile(path)  # noqa: S606
        except OSError:
            subprocess.Popen(["notepad.exe", str(path)])
    else:
        open_path(path)


def open_path(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - 로컬 결과 폴더 열기
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class SettingsDialog(tk.Toplevel):
    # (설정 키, 라벨, 가리기). "ai.xxx"는 ai 항목 아래에 저장한다.
    FIELDS = [
        ("naver_client_id", "네이버 Client ID", False),
        ("naver_client_secret", "네이버 Client Secret", True),
        ("anthropic_api_key", "Claude API 키", True),
        ("gemini_api_key", "Gemini API 키", True),
        ("ai.gemini_model", "Gemini 모델", False),
        ("my_press", "우리 매체 이름", False),
    ]

    def __init__(self, master, config):
        super().__init__(master)
        self.title("설정")
        self.resizable(False, False)
        self.transient(master)
        self.config_data = config
        self.vars = {}
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        for row, (key, label, secret) in enumerate(self.FIELDS):
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=self._get(key))
            ttk.Entry(frm, textvariable=var, width=46, show="•" if secret else "").grid(
                row=row, column=1, sticky="we", padx=(8, 0), pady=4)
            self.vars[key] = var
        row = len(self.FIELDS)
        ttk.Label(frm, text="검색 브랜드\n(쉼표·줄바꿈 구분)").grid(row=row, column=0, sticky="nw", pady=4)
        self.brands_box = tk.Text(frm, width=46, height=6, wrap="word", font=FONT, relief="solid", borderwidth=1)
        self.brands_box.insert("1.0", ", ".join(b["name"] for b in config.get("brands", [])))
        self.brands_box.grid(row=row, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(frm, foreground="#666", justify="left",
                  text="Gemini 모델 예: gemini-pro-latest(최신 Pro), gemini-3.8-flash(빠르고 저렴)\n"
                       "키는 이 프로그램 폴더의 config.json에 저장됩니다. 폴더째 공유하지 마세요.").grid(
            row=row + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        btns = ttk.Frame(frm)
        btns.grid(row=row + 2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="저장", command=self.save).pack(side="right", padx=6)
        self.saved = None
        self.grab_set()

    def _get(self, key):
        if key.startswith("ai."):
            return self.config_data.get("ai", {}).get(key[3:], "")
        return self.config_data.get(key, "")

    def save(self):
        values = {"ai": {}}
        for key, var in self.vars.items():
            if key.startswith("ai."):
                values["ai"][key[3:]] = var.get().strip()
            else:
                values[key] = var.get().strip()
        names = [n.strip() for n in re.split(r"[,\n]", self.brands_box.get("1.0", "end")) if n.strip()]
        values["brands"] = brands_from_names(list(dict.fromkeys(names)), self.config_data.get("brands", []))
        save_config(values)
        self.saved = values
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
        self.last_md = None
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
        self.search_brands = tk.BooleanVar(value=self.config_data.get("search_brands", True))
        self.brand_check = ttk.Checkbutton(hrs, variable=self.search_brands)
        self.brand_check.pack(side="left", padx=(16, 0))

        opts = ttk.Frame(src)
        opts.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.use_foreign = tk.BooleanVar(value=self.config_data.get("foreign", {}).get("enabled", True))
        ttk.Checkbutton(opts, text="외신도 수집(구글 뉴스)", variable=self.use_foreign).pack(side="left")
        self.use_bodies = tk.BooleanVar(value=self.config_data.get("bodies", {}).get("enabled", True))
        ttk.Checkbutton(opts, text="발제 후보 기사 본문 수집", variable=self.use_bodies).pack(side="left", padx=(16, 0))
        ttk.Label(opts, text="정렬").pack(side="left", padx=(16, 4))
        self.sort = tk.StringVar(value=SORT_CHOICES_REV.get(self.config_data.get("sort", "latest"), "최신순"))
        ttk.Combobox(opts, textvariable=self.sort, values=list(SORT_CHOICES), state="readonly",
                     width=8).pack(side="left")
        self._update_brand_label()

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
        ttk.Label(extra, text="AI 발제안·보도자료 점검·틀어보기").grid(row=1, column=0, sticky="w", pady=(8, 0))
        labels = [label for label, _ in AI_CHOICES]
        current = {v: label for label, v in AI_CHOICES}.get(self.config_data.get("ai_choice"), labels[0])
        self.ai_choice = tk.StringVar(value=current)
        ttk.Combobox(extra, textvariable=self.ai_choice, values=labels, state="readonly", width=22).grid(
            row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        extra.columnconfigure(1, weight=1)

        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="설정", command=self.open_settings).pack(side="left")
        ttk.Button(bar, text="샘플로 시험", command=self.run_sample).pack(side="left", padx=6)
        ttk.Button(bar, text="결과 폴더 열기", command=self.open_output).pack(side="left")
        ttk.Button(bar, text="마크다운 열기", command=self.open_markdown).pack(side="left", padx=6)
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
            self.config_data = _merge(self.config_data, dlg.saved)
            self._update_brand_label()
            self.log("설정을 저장했습니다.")

    def _update_brand_label(self):
        n = len(self.config_data.get("brands", []))
        self.brand_check.configure(text=f"브랜드 {n}개도 검색")

    def _ai_provider(self):
        return dict(AI_CHOICES).get(self.ai_choice.get())

    def open_markdown(self):
        if not self.last_md:
            files = sorted(Path(self.config_data["output_dir"]).glob("발제노트_*.md"))
            self.last_md = files[-1] if files else None
        if not self.last_md:
            messagebox.showinfo("발제 도우미", "아직 만든 발제 노트가 없습니다.")
            return
        open_text(self.last_md)

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
        provider = self._ai_provider()
        values = {"keywords": keywords, "lookback_hours": hours,
                  "search_brands": self.search_brands.get(), "ai_choice": provider,
                  "foreign": {"enabled": self.use_foreign.get()},
                  "bodies": {"enabled": self.use_bodies.get()},
                  "sort": SORT_CHOICES.get(self.sort.get(), "latest")}
        save_config(values)
        self.config_data = _merge(self.config_data, values)
        inputs = self.input_files if self.source.get() == "file" else []
        self._start(dict(inputs=inputs, materials_dir=self.materials_dir, hours=hours,
                         use_ai=bool(provider)))

    def run_sample(self):
        # 샘플은 가상 브랜드 목록으로 돌린다
        sample_cfg = json.loads(resource("samples/sample_config.json").read_text(encoding="utf-8"))
        self._start(dict(inputs=[resource("samples/sample_articles.json")],
                         materials_dir=resource("samples/materials"), hours=0,
                         use_ai=bool(self._ai_provider()), use_history=False),
                    overrides={"brands": sample_cfg["brands"], "sort": SORT_CHOICES.get(self.sort.get(), "latest")})

    def _start(self, kwargs, overrides=None):
        if self.worker and self.worker.is_alive():
            return
        self.run_btn.configure(state="disabled")
        self.progress.pack(side="right", padx=8)
        self.progress.start(12)
        provider = self._ai_provider() or "claude"  # tk 변수는 작업 스레드 밖에서 읽는다
        self.log("─" * 30)

        def work():
            try:
                cfg = _merge(self.config_data, overrides or {})
                cfg["ai"] = dict(cfg["ai"], provider=provider)
                result = pipeline.run(cfg, log=self.log, **kwargs)
                self.after(0, self._done, result, None)
            except pipeline.BaljeError as e:
                self.after(0, self._done, None, str(e))
            except Exception:  # 예상 못 한 오류도 창에 보여준다
                self.after(0, self._done, None, traceback.format_exc())

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _done(self, result, error):
        self.progress.stop()
        self.progress.pack_forget()
        self.run_btn.configure(state="normal")
        if error:
            self.log("오류: " + error)
            messagebox.showerror("발제 도우미", error.splitlines()[-1] if error else "오류")
            return
        html_path = result["html"]
        self.last_html, self.last_md = html_path, result["md"]
        self.log("[마크다운 열기]로 정리본(.md)을 볼 수 있습니다.")
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
        from google import genai  # noqa: F401
        lines.append("anthropic ok")
        lines.append("gemini sdk ok")
        sample_cfg = json.loads(resource("samples/sample_config.json").read_text(encoding="utf-8"))
        r = pipeline.run(_merge(load_config(), sample_cfg), inputs=[resource("samples/sample_articles.json")],
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
    from .llm import call_gemini
    msg = call_gemini("x", "hi", {"gemini_api_key": "selftest-invalid", "ai": {"gemini_model": "gemini-pro-latest"}})
    if "API 키가 올바르지 않습니다" not in msg:
        raise RuntimeError("gemini: " + msg)
    lines = ["naver https ok", "anthropic https ok", "gemini https ok"]

    from . import collect
    got = collect.fetch_google_news("Hyundai Motor")
    if not got:
        raise RuntimeError("google news: 결과 없음")
    lines.append(f"google news ok {len(got)} items, first: {got[0].press} | {got[0].title[:60]}")
    # 본문 추출은 사이트 구조에 좌우되므로 결과만 기록한다(실패해도 점검 실패로 보지 않음)
    try:
        raw, cs = collect._http_get("https://news.naver.com/main/ranking/popularDay.naver")
        page = collect._decode(raw, cs)
        m = re.search(r"https://n\.news\.naver\.com/(?:mnews/)?article/\d+/\d+", page)
        if m:
            body = collect.fetch_body(collect.Article(title="", link=m.group(0)))
            lines.append(f"naver body {'ok' if body else 'EMPTY'} {len(body)} chars {m.group(0)} :: {body[:80]!r}")
        else:
            lines.append("naver body: 랭킹 페이지에서 기사 링크를 못 찾음")
    except Exception as e:  # noqa: BLE001
        lines.append(f"naver body check error: {e}")
    return lines


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    prepare_workdir()
    App().mainloop()


if __name__ == "__main__":
    main()
