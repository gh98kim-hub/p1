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
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from osint import watchlist as osint_watchlist
from osint.watchlist import WatchlistError

from . import pipeline
from .llm import claude_code_status, open_login_window
from . import board as board_mod
from .dashboard import Dashboard
from .viewer import ReportViewer

INSTALL_HELP = """구독(Pro·Max)으로 쓰려면 Anthropic의 공식 프로그램 'Claude Code'가 필요합니다.

1) 설치: 시작 메뉴에서 'PowerShell'을 열고 아래 한 줄을 붙여 넣고 엔터
   irm https://claude.ai/install.ps1 | iex

2) 설치가 끝나면 이 프로그램을 껐다 켭니다.

3) [설정] → [Claude 로그인]을 누르면 새 창과 브라우저가 열립니다.
   Claude 계정(구독)으로 로그인하면 됩니다.

4) [상태 확인]에 '로그인됨: 구독 계정'이 나오면 준비 끝.

이 프로그램은 로그인 정보를 저장하지 않습니다. 글쓰기는 기자님 PC의 Claude Code가 하고,
사용량은 구독 요금제 한도에서 차감됩니다."""
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
        ("anthropic_api_key", "Claude API 키(API 방식일 때)", True),
        ("ai.claude_code_model", "구독 방식 모델(비우면 기본)", False),
        ("gemini_api_key", "Gemini API 키", True),
        ("ai.gemini_model", "Gemini 모델", False),
        ("my_press", "우리 매체 이름", False),
        ("courtlistener_token", "CourtListener 토큰(미국 법원)", True),
        ("sec_email", "SEC 연락처 이메일", False),
        ("telegram_bot_token", "텔레그램 봇 토큰(선택)", True),
        ("telegram_chat_id", "텔레그램 채팅 ID(선택)", False),
    ]

    def __init__(self, master, config):
        super().__init__(master)
        self.title("설정")
        self.resizable(False, False)
        self.transient(master)
        self.config_data = config
        self.vars = {}
        cf = ttk.LabelFrame(self, text="Claude 연결 방식", padding=10)
        cf.pack(fill="x", padx=14, pady=(14, 0))
        self.claude_auth = tk.StringVar(value=config.get("claude_auth", "api"))
        ttk.Radiobutton(cf, text="구독 로그인(Claude Pro·Max) — Claude Code로 연결, 요금제 안에서 사용",
                        value="subscription", variable=self.claude_auth).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(cf, text="API 키 — 사용한 만큼 따로 과금", value="api",
                        variable=self.claude_auth).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Button(cf, text="상태 확인", command=self.check_claude).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Button(cf, text="Claude 로그인", command=self.login_claude).grid(row=2, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Button(cf, text="설치 안내", command=self.install_help).grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.claude_status = ttk.Label(cf, foreground="#666", text="")
        self.claude_status.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

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
                       "SEC는 자동 접속자에게 연락처를 요구합니다. 비워두면 SEC 공시 수집이 막힐 수 있습니다.\n"
                       "키는 이 프로그램 폴더의 config.json에 저장됩니다. 폴더째 공유하지 마세요.").grid(
            row=row + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        btns = ttk.Frame(frm)
        btns.grid(row=row + 2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="저장", command=self.save).pack(side="right", padx=6)
        self.saved = None
        self.grab_set()

    def check_claude(self):
        installed, logged_in, msg = claude_code_status()
        self.claude_status.configure(text=msg, foreground="#1d7a46" if logged_in else "#9a5b00")

    def login_claude(self):
        if not open_login_window():
            self.install_help()
            return
        self.claude_status.configure(
            text="새 창에서 브라우저 로그인을 마친 뒤 [상태 확인]을 누르세요.", foreground="#666")

    def install_help(self):
        messagebox.showinfo("Claude Code 설치", INSTALL_HELP, parent=self)

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
        values["claude_auth"] = self.claude_auth.get()
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
        self._drain_id = self.after(100, self._drain_log)
        if not (self.config_data.get("naver_client_id") or os.environ.get("NAVER_CLIENT_ID")):
            self.log("처음이면 [설정]에서 네이버 API 키를 넣으세요. 키 없이 [샘플로 시험]도 해볼 수 있습니다.\n")

    # ------------------------------------------------------------ 화면 구성
    def _build(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        nb = ttk.Notebook(root)
        nb.pack(fill="x")
        tab1 = ttk.Frame(nb, padding=10)
        nb.add(tab1, text="국내 발제 노트")
        tab2 = ttk.Frame(nb, padding=10)
        nb.add(tab2, text="OSINT 레이더")
        tab3 = ttk.Frame(nb, padding=10)
        nb.add(tab3, text="역추적·팩트체크")
        self.run_buttons = []

        src = ttk.LabelFrame(tab1, text="기사 가져오기", padding=10)
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

        extra = ttk.LabelFrame(tab1, text="추가 자료 · AI", padding=10)
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

        bar = ttk.Frame(tab1)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="설정", command=self.open_settings).pack(side="left")
        ttk.Button(bar, text="샘플로 시험", command=self.run_sample).pack(side="left", padx=6)
        ttk.Button(bar, text="결과 폴더 열기", command=self.open_output).pack(side="left")
        ttk.Button(bar, text="결과 보기", command=self.open_markdown).pack(side="left", padx=6)
        self.run_btn = ttk.Button(bar, text="발제 노트 만들기", command=self.run_main)
        self.run_btn.pack(side="right")
        self.run_buttons.append(self.run_btn)
        self._build_osint(tab2)
        self._build_reverse(tab3)

        status = ttk.Frame(root)
        status.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=160)  # 실행 중에만 표시

        self.log_box = tk.Text(root, height=14, wrap="word", font=FONT, state="disabled",
                               relief="solid", borderwidth=1)
        self.log_box.pack(fill="both", expand=True, pady=(8, 0))

    def _ai_combo(self, parent):
        return ttk.Combobox(parent, textvariable=self.ai_choice, values=[label for label, _ in AI_CHOICES],
                            state="readonly", width=22)

    def _build_osint(self, tab):
        ocfg = self.config_data["osint"]
        from osint.classify import CHANNEL_KIND, KIND_ORDER, KINDS
        chf = ttk.LabelFrame(tab, text="수집 채널", padding=(10, 6))
        chf.pack(fill="x")
        self.channel_vars = {}
        for r, kind in enumerate(KIND_ORDER):
            ttk.Label(chf, text=KINDS[kind], foreground="#1d3d6e", font=(FONT[0], FONT[1], "bold")).grid(
                row=r, column=0, sticky="nw", padx=(0, 12), pady=3)
            row = ttk.Frame(chf)
            row.grid(row=r, column=1, sticky="w", pady=3)
            keys = [k for k in ocfg["channels"] if CHANNEL_KIND.get(k, "media") == kind]
            for i, key in enumerate(keys):
                ch = ocfg["channels"][key]
                var = tk.BooleanVar(value=ch.get("enabled", True))
                ttk.Checkbutton(row, text=ch.get("name", key), variable=var).grid(
                    row=i // 5, column=i % 5, sticky="w", padx=(0, 14), pady=1)
                self.channel_vars[key] = var
        opt = ttk.Frame(tab)
        opt.pack(fill="x", pady=(10, 0))
        ttk.Label(opt, text="최근").pack(side="left")
        self.osint_days = tk.StringVar(value=str(ocfg.get("lookback_days", 7)))
        ttk.Spinbox(opt, from_=1, to=60, textvariable=self.osint_days, width=4).pack(side="left", padx=4)
        ttk.Label(opt, text="일 · 자동 실행").pack(side="left")
        self.osint_auto = tk.StringVar(value=str(ocfg.get("auto_minutes", 0)))
        ttk.Spinbox(opt, from_=0, to=1440, increment=30, textvariable=self.osint_auto, width=5).pack(side="left", padx=4)
        ttk.Label(opt, text="분마다(0=끔) · AI").pack(side="left")
        self._ai_combo(opt).pack(side="left", padx=4)
        qa = ttk.Frame(tab)
        qa.pack(fill="x", pady=(10, 0))
        ttk.Label(qa, text="추적 대상 추가").pack(side="left")
        self.watch_quick = tk.StringVar()
        qe = ttk.Entry(qa, textvariable=self.watch_quick, width=44)
        qe.pack(side="left", padx=4, fill="x", expand=True)
        qe.bind("<Return>", lambda e: self.quick_add_watch())
        self.watch_quick_prio = tk.StringVar(value=osint_watchlist.PRIORITY_LABEL["mid"])
        ttk.Combobox(qa, textvariable=self.watch_quick_prio, values=list(osint_watchlist.PRIORITY_LABEL.values()),
                     state="readonly", width=5).pack(side="left", padx=4)
        ttk.Button(qa, text="추가", command=self.quick_add_watch).pack(side="left")
        ttk.Label(tab, text="쉼표로 구분 — 첫 단어가 대표 이름. 예) 현대모비스, Hyundai Mobis, 现代摩比斯 (영문이 있어야 해외 자료에서 찾습니다)",
                  foreground="#888").pack(anchor="w")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="추적 대상 편집", command=self.edit_watchlist).pack(side="left")
        ttk.Button(bar, text="추적 대상 다시 읽기", command=self.reload_watchlist).pack(side="left", padx=6)
        ttk.Button(bar, text="설정", command=self.open_settings).pack(side="left")
        btn = ttk.Button(bar, text="레이더 실행", command=self.run_radar)
        btn.pack(side="right")
        ttk.Button(bar, text="결과 폴더", command=self.open_output).pack(side="right", padx=6)
        ttk.Button(bar, text="결과 보기", command=lambda: self.open_latest("OSINT결과_*.json", "OSINT리포트_*.md")).pack(side="right")
        self.run_buttons.append(btn)
        ttk.Label(tab, foreground="#666", justify="left",
                  text="정부·공공 자료(SEC·법원·NHTSA·연방관보·주정부·EU·중국·한국 정부), 기업 발표, 언론을 나눠 모읍니다.\n"
                       "결과 화면 왼쪽에서 종류별로 골라 보고, [원문 열기]로 1차 자료를 엽니다. 미국 법원은 CourtListener 토큰을 씁니다.\n"
                       "국내 보도 건수는 네이버 키가 있을 때 자동 검색합니다. '선제 보도 후보'는 확인 취재 뒤 판단하세요.").pack(
            anchor="w", pady=(8, 0))
        self.auto_job = None

    def _build_reverse(self, tab):
        ttk.Label(tab, text="타사 기사 URL 또는 기사 본문을 붙여 넣으세요").pack(anchor="w")
        self.reverse_box = tk.Text(tab, height=7, wrap="word", font=FONT, relief="solid", borderwidth=1)
        self.reverse_box.pack(fill="x", pady=(4, 0))
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Label(bar, text="AI").pack(side="left")
        self._ai_combo(bar).pack(side="left", padx=4)
        ttk.Label(bar, foreground="#666", text="(AI 없이도 추적 대상 목록으로 1차 출처 후보는 찾습니다)").pack(side="left", padx=6)
        ttk.Button(bar, text="결과 보기", command=lambda: self.open_latest("역추적결과_*.json", "역추적_*.md")).pack(side="right", padx=6)
        btn = ttk.Button(bar, text="역추적 실행", command=self.run_reverse)
        btn.pack(side="right")
        self.run_buttons.append(btn)

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
        self._drain_id = self.after(100, self._drain_log)

    def destroy(self):
        if getattr(self, "_drain_id", None):
            self.after_cancel(self._drain_id)
        super().destroy()

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
        if self.last_md:
            self.show(self.last_md)
        else:
            self.open_latest("발제결과_*.json", "발제노트_*.md")

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
        def job(cfg):
            return pipeline.run(cfg, log=self.log, **kwargs)
        self._run_job(job, self._done_notes, overrides)

    def _run_job(self, job, on_done, overrides=None):
        """작업을 별도 스레드로 돌리고 끝나면 on_done(result)을 창 스레드에서 부른다."""
        if self.worker and self.worker.is_alive():
            return False
        for b in self.run_buttons:
            b.configure(state="disabled")
        self.progress.pack(side="right")
        self.progress.start(12)
        provider = self._ai_provider() or "claude"  # tk 변수는 작업 스레드 밖에서 읽는다
        self.log("─" * 30)

        def work():
            try:
                cfg = _merge(self.config_data, overrides or {})
                cfg["ai"] = dict(cfg["ai"], provider=provider)
                result = job(cfg)
                self.after(0, self._finish, on_done, result, None)
            except (pipeline.BaljeError, RuntimeError, WatchlistError) as e:
                self.after(0, self._finish, on_done, None, str(e))
            except Exception:  # 예상 못 한 오류도 창에 보여준다
                self.after(0, self._finish, on_done, None, traceback.format_exc())

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        return True

    def _finish(self, on_done, result, error):
        self.progress.stop()
        self.progress.pack_forget()
        for b in self.run_buttons:
            b.configure(state="normal")
        if error:
            self.log("오류: " + error)
            if not getattr(self, "_auto_running", False):
                messagebox.showerror("발제 도우미", error.splitlines()[-1] if error else "오류")
            return
        on_done(result)

    def _done_notes(self, result):
        self.last_html, self.last_md = result["html"], result.get("json") or result["md"]
        self.log("완료. [결과 보기]로 다시 볼 수 있습니다.")
        self.show(self.last_md)

    # ------------------------------------------------------------ OSINT
    def _watchlist_path(self):
        return Path(self.config_data["osint"]["watchlist_file"])

    def edit_watchlist(self):
        """추적 대상을 키워드 칸으로 고치는 창(메모장 편집은 창 안의 버튼으로)."""
        from .watch_editor import WatchlistEditor
        try:
            WatchlistEditor(self, self._watchlist_path(), on_saved=self.reload_watchlist, open_text=open_text)
        except WatchlistError as e:
            messagebox.showerror("추적 대상", f"{e}\n\n메모장으로 열어 고치세요.")
            open_text(osint_watchlist.ensure_file(self._watchlist_path()))

    def quick_add_watch(self):
        """OSINT 탭의 '추적 대상 추가' 칸: 첫 키워드가 대표 이름, 나머지는 다른 표기."""
        text = self.watch_quick.get().strip()
        if not text:
            return
        path = osint_watchlist.ensure_file(self._watchlist_path())
        try:
            data = osint_watchlist.load(path)
            e, created = osint_watchlist.quick_add(data, text, self.watch_quick_prio_value())
            osint_watchlist.save(data, path)
        except (WatchlistError, OSError) as err:
            messagebox.showerror("추적 대상", str(err))
            return
        self.watch_quick.set("")
        self.log(f"추적 대상 '{e['name']}' " + ("추가" if created else "키워드 보탬")
                 + f" — 한국어 {len(e['ko'])} · 영문 {len(e['en'])} · 중문 {len(e['zh'])}개")
        for w in osint_watchlist.warnings(e):
            self.log("  주의: " + w)

    def watch_quick_prio_value(self):
        return {v: k for k, v in osint_watchlist.PRIORITY_LABEL.items()}.get(self.watch_quick_prio.get(), "mid")

    def reload_watchlist(self):
        try:
            w = osint_watchlist.load(osint_watchlist.ensure_file(self._watchlist_path()))
        except WatchlistError as e:
            messagebox.showerror("추적 대상", str(e))
            return
        by = {}
        for e in w["entities"]:
            by[e["priority"]] = by.get(e["priority"], 0) + 1
        self.log(f"추적 대상 {len(w['entities'])}곳(high {by.get('high', 0)} · mid {by.get('mid', 0)} · "
                 f"low {by.get('low', 0)}) · 지역 {len(w.get('locations', []))}곳 읽음")

    def _save_osint_options(self):
        try:
            days = int(float(self.osint_days.get()))
            auto = int(float(self.osint_auto.get()))
        except ValueError:
            messagebox.showwarning("OSINT", "기간·자동 실행 간격은 숫자로 넣으세요.")
            return False
        values = {"ai_choice": self._ai_provider(), "osint": {
            "lookback_days": days, "auto_minutes": auto,
            "channels": {k: {"enabled": v.get()} for k, v in self.channel_vars.items()}}}
        save_config(values)
        self.config_data = _merge(self.config_data, values)
        return True

    def run_radar(self, auto=False):
        from osint import radar
        if not auto and not self._save_osint_options():
            return
        self._auto_running = auto
        use_ai = bool(self._ai_provider())
        started = self._run_job(lambda cfg: radar.run(cfg, log=self.log, use_ai=use_ai),
                                lambda res: self._done_radar(res, auto))
        if not started and auto:
            self.log("다른 작업이 진행 중이라 자동 실행을 다음으로 미룹니다.")
            self._schedule_auto()

    def show(self, path):
        """결과를 프로그램 안 결과 화면으로 연다. JSON은 분류·목록·상세 화면, 예전 마크다운은 문서 보기."""
        path = Path(path)
        if path.suffix.lower() == ".json":
            try:
                data = board_mod.load(path)
            except (OSError, ValueError) as e:
                messagebox.showerror("결과 보기", f"결과 파일을 읽지 못했습니다: {e}")
                return
            Dashboard(self, data, path, open_path=open_path, open_text=open_text,
                      translate_config=self._translate_config)
        else:
            ReportViewer(self, path, open_text=open_text, open_path=open_path)

    def _translate_config(self):
        """결과 화면 [AI 번역]용 설정. 첫 화면에서 고른 AI를 먼저 쓰고, '사용 안 함'이면 연결된 쪽."""
        cfg = _merge(self.config_data, {})
        cfg["ai"] = dict(cfg["ai"], provider=self._ai_provider() or cfg["ai"].get("provider", "claude"))
        return cfg

    def open_latest(self, *patterns):
        """가장 최근 결과를 연다. 앞쪽 형식(결과 화면 JSON)을 우선한다."""
        out = Path(self.config_data["output_dir"])
        for pattern in patterns:
            files = sorted(out.glob(pattern), key=lambda p: p.stat().st_mtime)
            if files:
                self.show(files[-1])
                return
        messagebox.showinfo("발제 도우미", "아직 만든 결과가 없습니다.")

    def _done_radar(self, result, auto):
        self.log(f"레이더 완료: 자료 {len(result['signals'])}건 · 발제 후보 {len(result['cands'])}건")
        self.log("[결과 보기]로 다시 볼 수 있습니다.")
        if not auto:
            self.show(result.get("json") or result["md"])
        self._schedule_auto()

    def _schedule_auto(self):
        if self.auto_job:
            self.after_cancel(self.auto_job)
            self.auto_job = None
        minutes = self.config_data["osint"].get("auto_minutes", 0)
        if minutes and minutes > 0:
            self.auto_job = self.after(int(minutes * 60000), lambda: self.run_radar(auto=True))
            self.log(f"{minutes}분 뒤 레이더를 다시 실행합니다(창을 닫으면 멈춤).")

    def run_reverse(self):
        from osint import reverse
        text = self.reverse_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("역추적", "기사 URL이나 본문을 넣으세요.")
            return
        self._auto_running = False
        use_ai = bool(self._ai_provider())
        self._run_job(lambda cfg: reverse.run(text, cfg, log=self.log, use_ai=use_ai),
                      lambda res: self.show(res.get("json") or res["md"]))


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
        app2 = App()
        v = ReportViewer(app2, r["md"])
        v.update()
        lines.append(f"viewer ok {len(v.links)} links")
        d = Dashboard(app2, board_mod.load(r["json"]), r["json"], translate_config=app2._translate_config)
        d.update()
        lines.append(f"dashboard ok {len(d.table.get_children())} rows in {d.current_group}, "
                     f"{len(d._widgets)} buttons, translate button {d.tr_btn.winfo_manager() or 'hidden'}")
        from .watch_editor import WatchlistEditor
        ed = WatchlistEditor(app2, "selftest_out/watchlist.json")
        ed.update()
        lines.append(f"watchlist editor ok {len(ed.ent_list.get_children())} entities")
        ed.destroy()
        app2.destroy()
        from osint import radar, reverse  # noqa: F401 - exe에 포함됐는지 확인
        w = osint_watchlist.load()
        lines.append(f"osint watchlist ok {len(w['entities'])} entities")
        if os.environ.get("BALJE_SELFTEST_NET") == "1":
            lines += _net_checks()
        code = 0
    except Exception:
        lines.append(traceback.format_exc())
        code = 1
    Path(result_file).write_text("\n".join(lines), encoding="utf-8")
    return code


def _osint_net_checks():
    """OSINT 채널 실접속 결과를 기록한다(사이트 사정에 좌우되므로 실패해도 점검 실패로 보지 않음)."""
    from datetime import datetime, timedelta, timezone

    from osint import http as ohttp
    from osint.sources import courts, news, nhtsa, sec_edgar
    out = []
    now = datetime.now(timezone.utc)
    w = osint_watchlist.load()

    def rec(label, fn):
        try:
            out.append(f"osint {label}: {fn()}")
        except Exception as e:  # noqa: BLE001
            out.append(f"osint {label}: ERROR {type(e).__name__}: {str(e)[:160]}")

    def sec():
        raw = ohttp.get_json(sec_edgar.FTS_URL, {"q": '"Hyundai Motor"', "dateRange": "custom",
                                                  "startdt": (now - timedelta(days=60)).strftime("%Y-%m-%d"),
                                                  "enddt": now.strftime("%Y-%m-%d")},
                             sec_edgar.headers(os.environ.get("BALJE_SEC_EMAIL", "")))
        sigs = sec_edgar.parse_fts(raw)
        return f"{len(sigs)} hits; first={sigs[0].title[:70] if sigs else '-'}; keys={sorted(raw)[:6]}"

    def nh():
        import urllib.error
        ms = nhtsa.models("hyundai", now.year)
        res = [f"{len(ms)} models"]
        for m in ms[:4]:
            try:
                recs = nhtsa.recalls_for("hyundai", m, now.year)
                res.append(f"{m}: {len(recs)} recalls"
                           + (f" (date sample {recs[0].get('ReportReceivedDate')})" if recs else ""))
            except urllib.error.HTTPError as e:
                res.append(f"{m}: HTTP {e.code} {e.read(160).decode('utf-8', 'replace')!r}")
        return "; ".join(res)

    def cl():
        sigs = courts.search('"Hyundai Motor"', os.environ.get("BALJE_CL_TOKEN", ""), now - timedelta(days=60), "r")
        return f"{len(sigs)} results; first={sigs[0].title[:70] if sigs else '-'}"

    def gn(key):
        def f():
            from balje.config import load_config
            ch = load_config("none.json")["osint"]["channels"][key]
            q = news.build_queries(ch, w, 7)
            sigs = news.search_channel(key, dict(ch, max_queries=2), w, 7, sleep=0.2)
            from osint.classify import kind_of
            kinds = {}
            for x in sigs:
                kinds[kind_of(x)] = kinds.get(kind_of(x), 0) + 1
            doms = sorted({x.meta.get("domain", "?") for x in sigs})[:6]
            return (f"{len(q)} queries; {len(sigs)} items from 2; kinds={kinds}; domains={doms}; "
                    f"first={sigs[0].title[:60] if sigs else '-'}")
        return f

    def fr(term):
        def f():
            from osint.sources import federal_register
            sigs = federal_register.search(term, now - timedelta(days=60), 20)
            return f"{len(sigs)} docs; first={sigs[0].published.date() if sigs else '-'} {sigs[0].title[:60] if sigs else '-'}"
        return f

    def krgov():
        from balje.config import load_config
        from osint.classify import kind_of
        ch = load_config("none.json")["osint"]["channels"]["kr_gov"]
        sigs = news.search_topics("kr_gov", dict(ch, terms=ch["terms"][:7]), 7, sleep=0.2)
        kinds = {}
        for x in sigs:
            kinds[kind_of(x)] = kinds.get(kind_of(x), 0) + 1
        doms = sorted({x.meta.get("domain", "?") for x in sigs})[:6]
        return f"{len(sigs)} items; kinds={kinds}; domains={doms}; first={sigs[0].title[:50] if sigs else '-'}"

    rec("sec", sec)
    rec("nhtsa", nh)
    rec("courts(no token)", cl)
    rec("fed_register single", fr('"Hyundai"'))
    rec("fed_register OR", fr('"Hyundai" | "Kia"'))
    rec("fed_register topic", fr("lithium-ion batteries"))
    rec("kr_gov", krgov)


    for key in ("us_federal", "gov_press", "eu_comp", "china_gov", "pr_wire", "local_media", "global_media",
                "china_media"):
        rec(key, gn(key))
    return out


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
    lines += _osint_net_checks()
    # 본문 추출은 사이트 구조에 좌우되므로 결과만 기록한다(실패해도 점검 실패로 보지 않음)
    try:
        raw, cs = collect._http_get("https://news.naver.com/main/ranking/popularDay.naver")
        page = collect._decode(raw, cs)
        links = list(dict.fromkeys(re.findall(r"https://n\.news\.naver\.com/(?:mnews/)?article/\d+/\d+", page)))
        for link in links[:3]:
            body = collect.fetch_body(collect.Article(title="", link=link))
            raw2, cs2 = collect._http_get(link)
            page2 = collect._decode(raw2, cs2)
            lines.append(f"naver body {'ok' if body else 'EMPTY'} {len(body)} chars {link} "
                         f"(html {len(page2)}, dic_area={'dic_area' in page2}) :: {body[:60]!r}")
        if not links:
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
