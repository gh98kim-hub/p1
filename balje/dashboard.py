"""결과 화면(대시보드): 왼쪽 분류 · 가운데 목록 · 아래 상세. 링크는 [원문 열기] 버튼으로 연다."""

import re
import threading
import tkinter as tk
import urllib.parse
import webbrowser
from pathlib import Path
from tkinter import ttk

from . import board as board_mod
from .viewer import line_style, parse_inline

FAMILY = "Malgun Gothic"
_BARE_URL = re.compile(r"\s*(?:URL\s*[:：]\s*)?(?:[-•◦·]\s*)?(https?://\S+)\s*")


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _ai_label(cfg):
    from .llm import available_provider
    return {"claude": "Claude", "gemini": "Gemini"}.get(available_provider(cfg) or "", "AI")


def _domain(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


class Dashboard(tk.Toplevel):
    def __init__(self, master, data, path=None, open_path=None, open_text=None, translate_config=None):
        """translate_config: [AI 번역]에 쓸 설정을 돌려주는 함수(창 스레드에서 부름). 없으면 번역 버튼을 숨긴다."""
        super().__init__(master)
        self.data = data
        self._tr_config = translate_config
        self._busy = False
        self.path = Path(path) if path else None
        self._open_path = open_path
        self._open_text = open_text
        self.size = 10
        self.sort_state = (None, False)
        self.current_group = None
        self.current_row = None
        self.rows_by_id = {r["id"]: r for r in data["rows"]}
        self.groups = {g["key"]: g for g in data["groups"]}
        self.counts = {}
        for r in data["rows"]:
            for g in r["groups"]:
                self.counts[g] = self.counts.get(g, 0) + 1
        self._link_n = 0
        self._widgets = []

        self.title(data.get("title", "결과"))
        self.geometry("1320x860")
        self.minsize(900, 560)
        self._style()
        self._build()
        self._fill_groups()
        self._select_first()

    # ------------------------------------------------------------ 화면
    def _style(self):
        st = ttk.Style(self)
        st.configure("Board.Treeview", rowheight=28, font=(FAMILY, 10))
        st.configure("Board.Treeview.Heading", font=(FAMILY, 10, "bold"))
        st.configure("Side.Treeview", rowheight=30, font=(FAMILY, 10))

    def _build(self):
        head = ttk.Frame(self, padding=(14, 10, 14, 4))
        head.pack(fill="x")
        tk.Label(head, text=self.data.get("title", ""), font=(FAMILY, 15, "bold"), anchor="w").pack(fill="x")
        for line in self.data.get("summary", []):
            tk.Label(head, text=line, font=(FAMILY, 10), fg="#444", anchor="w", justify="left",
                     wraplength=1250).pack(fill="x")

        bar = ttk.Frame(self, padding=(14, 4, 14, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text="찾기").pack(side="left")
        self.search = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.search, width=34)
        ent.pack(side="left", padx=(4, 10))
        self.search.trace_add("write", lambda *_: self._fill_rows())
        self.only_new = tk.BooleanVar(value=False)
        if any(r.get("new") for r in self.data["rows"]):
            ttk.Checkbutton(bar, text="신규 이슈만" if self.data.get("kind") == "notes" else "새로 잡힌 것만",
                            variable=self.only_new,
                            command=self._fill_rows).pack(side="left")
        self.count_label = ttk.Label(bar, text="", foreground="#666")
        self.count_label.pack(side="left", padx=12)
        if self._tr_config:
            self.list_tr_btn = ttk.Button(bar, text="목록 제목 AI 번역", command=self._translate_list)
            self.list_tr_btn.pack(side="right", padx=(6, 0))
        if self.path:
            ttk.Button(bar, text="결과 폴더", command=self._folder).pack(side="right")
            md = self._md_file()
            if md and self._open_text:
                ttk.Button(bar, text="문서(마크다운)로 열기",
                           command=lambda: self._open_text(md)).pack(side="right", padx=6)
        ttk.Button(bar, text="글자 크게", command=lambda: self._zoom(1)).pack(side="right")
        ttk.Button(bar, text="글자 작게", command=lambda: self._zoom(-1)).pack(side="right", padx=6)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        left = ttk.Frame(body)
        self.side = ttk.Treeview(left, show="tree", style="Side.Treeview", selectmode="browse")
        self.side.column("#0", width=250)
        self.side.pack(fill="both", expand=True)
        self.side.bind("<<TreeviewSelect>>", lambda e: self._on_group())
        body.add(left, weight=0)

        right = ttk.PanedWindow(body, orient="vertical")
        body.add(right, weight=1)

        tbl = ttk.Frame(right)
        self.table = ttk.Treeview(tbl, show="headings", style="Board.Treeview", selectmode="browse")
        ys = ttk.Scrollbar(tbl, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=ys.set)
        self.table.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.table.tag_configure("odd", background="#f6f7f9")
        self.table.tag_configure("new", foreground="#0b4fa8")
        self.table.tag_configure("warn", foreground="#b3261e")
        self.table.bind("<<TreeviewSelect>>", lambda e: self._on_row())
        self.table.bind("<Double-1>", lambda e: self._open_current())
        self.table.bind("<Return>", lambda e: self._open_current())
        right.add(tbl, weight=2)

        det = ttk.Frame(right)
        act = ttk.Frame(det, padding=(0, 6, 0, 4))
        act.pack(fill="x")
        self.open_btn = ttk.Button(act, text="원문 열기", command=self._open_current, state="disabled")
        self.open_btn.pack(side="left")
        self.copy_btn = ttk.Button(act, text="링크 복사", command=self._copy_current, state="disabled")
        self.copy_btn.pack(side="left", padx=6)
        self.tr_btn = ttk.Button(act, text="AI 번역", command=self._translate_current)
        self.orig_btn = ttk.Button(act, text="원문 보기", command=self._toggle_original)
        if self._tr_config:
            self.tr_btn.pack(side="left", padx=(12, 0))
        self.site_label = ttk.Label(act, text="", foreground="#777")
        self.site_label.pack(side="left", padx=6)
        self.text = tk.Text(det, wrap="word", relief="solid", borderwidth=1, padx=16, pady=12,
                            cursor="arrow", spacing1=2, spacing3=2)
        dys = ttk.Scrollbar(det, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=dys.set)
        self.text.pack(side="left", fill="both", expand=True)
        dys.pack(side="right", fill="y")
        right.add(det, weight=3)
        self._tags()
        self.text.configure(state="disabled")

    def _tags(self):
        s = self.size
        t = self.text
        t.configure(font=(FAMILY, s))
        t.tag_configure("title", font=(FAMILY, s + 4, "bold"), spacing1=4, spacing3=6)
        t.tag_configure("sub", font=(FAMILY, s), foreground="#555", spacing3=6)
        t.tag_configure("h", font=(FAMILY, s + 1, "bold"), foreground="#1d3d6e", spacing1=12, spacing3=4)
        t.tag_configure("h3", font=(FAMILY, s, "bold"), foreground="#1d3d6e", spacing1=8)
        t.tag_configure("p", font=(FAMILY, s), lmargin1=2, lmargin2=2)
        t.tag_configure("b", font=(FAMILY, s, "bold"))
        t.tag_configure("note", font=(FAMILY, s - 1), foreground="#777")
        t.tag_configure("key", font=(FAMILY, s, "bold"), foreground="#555")
        t.tag_configure("item", lmargin1=12, lmargin2=30)
        t.tag_configure("linktext", font=(FAMILY, s), foreground="#222")
        t.tag_configure("extra", font=(FAMILY, s - 1), foreground="#777")
        t.tag_configure("inline", foreground="#0b57d0", underline=True)

    def _zoom(self, d):
        self.size = max(8, min(18, self.size + d))
        self._tags()
        ttk.Style(self).configure("Board.Treeview", font=(FAMILY, self.size), rowheight=self.size * 2 + 8)
        if self.current_row:
            self._render(self.current_row)

    # ------------------------------------------------------------ 분류·목록
    def _fill_groups(self):
        for g in self.data["groups"]:
            n = self.counts.get(g["key"], 0)
            parent = g["parent"] if g["parent"] in self.groups else ""
            self.side.insert(parent, "end", iid=g["key"], text=f"{g['label']}   {n}", open=True)

    def _select_first(self):
        order = [g["key"] for g in self.data["groups"]]
        pick = next((k for k in order if self.counts.get(k)), order[0] if order else None)
        if pick:
            self.side.selection_set(pick)
            self.side.see(pick)
            self._on_group()

    def _on_group(self):
        sel = self.side.selection()
        if not sel:
            return
        self.current_group = sel[0]
        g = self.groups[self.current_group]
        cols = self.data["columns"].get(g["cols"], [["항목", 500, True]])
        ids = [f"c{i}" for i in range(len(cols))]
        self.table.configure(columns=ids)
        for cid, (label, width, stretch) in zip(ids, cols):
            self.table.heading(cid, text=label, command=lambda c=cid: self._sort(c))
            self.table.column(cid, width=width, stretch=bool(stretch), anchor="w")
        self.sort_state = (None, False)
        self._fill_rows()

    def _visible_rows(self):
        q = self.search.get().strip().lower()
        out = []
        for r in self.data["rows"]:
            if self.current_group not in r["groups"]:
                continue
            if self.only_new.get() and not r.get("new"):
                continue
            if q and q not in " ".join(str(v) for v in self._values(r) + r["values"]).lower():
                continue
            out.append(r)
        col, rev = self.sort_state
        if col is not None:
            i = int(col[1:])

            def key(r):
                vals = self._values(r)
                v = vals[i] if i < len(vals) else ""
                n = _num(v)
                return (0, n, "") if n is not None else (1, 0, str(v))
            out.sort(key=key, reverse=rev)
        return out

    def _fill_rows(self):
        self.table.delete(*self.table.get_children())
        rows = self._visible_rows()
        for i, r in enumerate(rows):
            tags = ["odd"] if i % 2 else []
            if r.get("new"):
                tags.append("new")
            if r.get("warn"):
                tags.append("warn")
            self.table.insert("", "end", iid=r["id"], values=[str(v) for v in self._values(r)], tags=tags)
        total = self.counts.get(self.current_group, 0)
        self.count_label.configure(text=f"{len(rows)}건 표시" + (f" / 전체 {total}건" if len(rows) != total else ""))
        if rows:
            self.table.selection_set(rows[0]["id"])
            self.table.focus(rows[0]["id"])
        else:
            self.current_row = None
            self._render(None)

    def _sort(self, col):
        cur, rev = self.sort_state
        self.sort_state = (col, (not rev) if cur == col else False)
        self._fill_rows()

    def _on_row(self):
        sel = self.table.selection()
        if not sel:
            return
        self.current_row = self.rows_by_id.get(sel[0])
        self._render(self.current_row)

    # ------------------------------------------------------------ 상세
    def _render(self, row):
        t = self.text
        t.configure(state="normal")
        for w in self._widgets:
            w.destroy()
        self._widgets = []
        t.delete("1.0", "end")
        url = (row or {}).get("url", "")
        state = "normal" if url else "disabled"
        self.open_btn.configure(state=state)
        self.copy_btn.configure(state=state)
        self.site_label.configure(text=_domain(url))
        tr = (row or {}).get("tr") or {}
        if tr.get("detail"):
            self.orig_btn.configure(text="번역 보기" if row.get("show_orig") else "원문 보기")
            self.orig_btn.pack(side="left", padx=(6, 0), after=self.tr_btn)
        else:
            self.orig_btn.pack_forget()
        self.tr_btn.configure(state="disabled" if (self._busy or not row) else "normal")
        if not row:
            t.insert("end", "이 분류에는 자료가 없습니다.\n", "note")
            if self.current_group == "cand":
                t.insert("end", "\n이번 수집에서 발제 후보로 묶인 것이 없다. 왼쪽 '전체 자료'에서 정부·기업·언론 자료를 직접 볼 수 있다.\n", "note")
        else:
            detail = row.get("detail", [])
            if tr.get("detail") and not row.get("show_orig"):
                detail = tr["detail"]
                t.insert("end", f"AI 번역본({tr.get('by', 'AI')}) — 원문과 대조해 쓴다. [원문 보기]로 바꿔 볼 수 있다.\n", "note")
            for blk in detail:
                self._block(blk)
        t.configure(state="disabled")
        t.yview_moveto(0)

    def _block(self, blk):
        t = self.text
        kind, x = blk.get("t"), blk.get("x")
        if kind == "title":
            t.insert("end", x + "\n", "title")
        elif kind == "sub":
            t.insert("end", x + "\n", "sub")
        elif kind == "h":
            t.insert("end", x + "\n", "h")
        elif kind == "note":
            t.insert("end", x + "\n", "note")
        elif kind == "kv":
            for k, v in x:
                t.insert("end", f"{k}  ", ("key", "item"))
                t.insert("end", f"{v}\n", ("p", "item"))
        elif kind == "bullets":
            for i in x:
                t.insert("end", f"• {i}\n", ("p", "item"))
        elif kind == "checks":
            for i in x:
                t.insert("end", f"☐ {i}\n", ("p", "item"))
        elif kind == "link":
            self._link_line(x, blk.get("url", ""), blk.get("extra", ""))
        elif kind == "p":
            self._paragraph(x or "")

    def _button(self, label, cmd):
        b = tk.Button(self.text, text=label, command=cmd, font=(FAMILY, max(8, self.size - 1)), padx=6, pady=0,
                      relief="groove", bg="#eef3fb", activebackground="#d9e6fa", cursor="hand2")
        self._widgets.append(b)
        return b

    def _link_line(self, label, url, extra=""):
        t = self.text
        if url:
            t.window_create("end", window=self._button("원문 열기", lambda: self._open(url)), padx=2, pady=2)
            t.window_create("end", window=self._button("복사", lambda: self._copy(url)), padx=2, pady=2)
            t.insert("end", "  ")
        t.insert("end", label, ("linktext",))
        if extra:
            t.insert("end", "   " + extra, ("extra",))
        elif url:
            t.insert("end", "   " + _domain(url), ("extra",))
        t.insert("end", "\n")

    def _paragraph(self, text):
        """AI 초안처럼 긴 글. 제목(#)·목록은 정리하고, 한 줄짜리 주소는 버튼으로 바꾼다."""
        t = self.text
        for line in text.splitlines():
            kind, s = line_style(line)
            if kind == "skip":
                continue
            if kind == "rule":
                t.insert("end", "\n")
                continue
            m = _BARE_URL.fullmatch(s)
            if m:
                self._link_line("", m.group(1))
                continue
            tag = {"h1": "h", "h2": "h", "h3": "h3"}.get(kind, "p")
            for seg, typ, url in parse_inline(s):
                if typ == "link":
                    self._inline_link(seg, url, tag)
                else:
                    t.insert("end", seg, (tag, "b") if typ == "bold" else (tag,))
            t.insert("end", "\n", (tag,))

    def _inline_link(self, label, url, tag):
        self._link_n += 1
        name = f"lnk{self._link_n}"
        self.text.insert("end", label if not label.startswith("http") else _domain(label) + " ↗", (tag, "inline", name))
        self.text.tag_bind(name, "<Button-1>", lambda e, u=url: self._open(u))
        self.text.tag_bind(name, "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind(name, "<Leave>", lambda e: self.text.configure(cursor="arrow"))

    # ------------------------------------------------------------ AI 번역
    def _title_index(self):
        """지금 표에서 제목 칸(늘어나는 칸) 위치."""
        g = self.groups.get(self.current_group) or {}
        cols = self.data["columns"].get(g.get("cols"), [])
        return next((i for i, c in enumerate(cols) if c[2]), None)

    def _values(self, r):
        vals = list(r["values"])
        title = (r.get("tr") or {}).get("title")
        i = self._title_index()
        if title and i is not None and i < len(vals):
            vals[i] = title
        return vals

    def _run_translation(self, work, done, waiting):
        """번역은 시간이 걸리므로 별도 스레드로. 끝나면 창 스레드에서 done(결과) 또는 오류 표시."""
        if self._busy:
            return
        self._busy = True
        self.tr_btn.configure(state="disabled")
        if hasattr(self, "list_tr_btn"):
            self.list_tr_btn.configure(state="disabled")
        self.site_label.configure(text=waiting)

        def finish(result, error):
            self._busy = False
            self.tr_btn.configure(state="normal")
            if hasattr(self, "list_tr_btn"):
                self.list_tr_btn.configure(state="normal")
            if error:
                self.site_label.configure(text="번역 실패")
                from tkinter import messagebox
                messagebox.showwarning("AI 번역", error, parent=self)
                return
            done(result)

        box = []

        def bg():
            try:
                box.append((work(), None))
            except Exception as e:  # noqa: BLE001 - 화면에 이유를 보여준다
                box.append((None, str(e) or type(e).__name__))

        def poll():
            # 작업 스레드는 화면을 건드리지 않고, 창 스레드가 결과를 가져간다
            if box:
                finish(*box[0])
            elif self.winfo_exists():
                self.after(100, poll)

        threading.Thread(target=bg, daemon=True).start()
        self.after(100, poll)

    def _translator(self):
        from .translate import translate_texts
        cfg = self._tr_config()
        return lambda texts: translate_texts(texts, cfg, log=lambda m: None), _ai_label(cfg)

    def _translate_current(self):
        row = self.current_row
        if not row or not self._tr_config:
            return
        tr = row.get("tr") or {}
        if tr.get("detail"):          # 이미 번역함 → 번역본으로 돌아간다
            row["show_orig"] = False
            self._render(row)
            return
        texts = board_mod.detail_texts(row.get("detail", []))
        i = self._title_index()
        if i is not None and i < len(row["values"]):
            texts["row_title"] = str(row["values"][i])
        fn, label = self._translator()

        def done(out):
            if not out:
                self.site_label.configure(text="번역할 외국어가 없습니다")
                return
            new = dict(row.get("tr") or {}, by=label)
            if out.get("row_title"):
                new["title"] = out.pop("row_title")
            if out:
                new["detail"] = board_mod.apply_texts(row.get("detail", []), out)
            row["tr"], row["show_orig"] = new, False
            self._after_translation([row])
            self.site_label.configure(text=f"{label}로 번역했습니다")

        self._run_translation(lambda: fn(texts), done, f"{label}로 번역 중… (구독 로그인은 1~2분 걸릴 수 있음)")

    def _translate_list(self):
        if not self._tr_config:
            return
        i = self._title_index()
        if i is None:
            return
        rows = [r for r in self._visible_rows() if not (r.get("tr") or {}).get("title")][:200]
        texts = {r["id"]: str(r["values"][i]) for r in rows if i < len(r["values"])}
        fn, label = self._translator()
        by_id = {r["id"]: r for r in rows}

        def done(out):
            if not out:
                self.site_label.configure(text="번역할 외국어 제목이 없습니다")
                return
            changed = []
            for rid, text in out.items():
                if rid in by_id:
                    by_id[rid]["tr"] = dict(by_id[rid].get("tr") or {}, title=text, by=label)
                    changed.append(by_id[rid])
            self._after_translation(changed)
            self.site_label.configure(text=f"{label}로 제목 {len(changed)}건 번역했습니다")

        self._run_translation(lambda: fn(texts), done, f"{label}로 제목 {len(texts)}건 번역 중…")

    def _after_translation(self, rows):
        for r in rows:
            if self.table.exists(r["id"]):
                self.table.item(r["id"], values=[str(v) for v in self._values(r)])
        if self.current_row in rows:
            self._render(self.current_row)
        if self.path:
            try:
                board_mod.save(self.data, self.path)   # 다시 열어도 번역이 남게
            except OSError:
                pass

    def _toggle_original(self):
        row = self.current_row
        if row and (row.get("tr") or {}).get("detail"):
            row["show_orig"] = not row.get("show_orig")
            self._render(row)

    # ------------------------------------------------------------ 동작
    def _open(self, url):
        if url:
            webbrowser.open(url)

    def _copy(self, url):
        self.clipboard_clear()
        self.clipboard_append(url)
        self.site_label.configure(text="링크를 복사했습니다")

    def _open_current(self):
        if self.current_row and self.current_row.get("url"):
            self._open(self.current_row["url"])

    def _copy_current(self):
        if self.current_row and self.current_row.get("url"):
            self._copy(self.current_row["url"])

    def _md_file(self):
        name = (self.data.get("files") or {}).get("md")
        if name and self.path:
            p = self.path.parent / name
            return p if p.exists() else None
        return None

    def _folder(self):
        if self._open_path and self.path:
            self._open_path(self.path.parent.resolve())
