"""추적 대상 편집 창: 메모장(JSON) 대신 이름·키워드 칸으로 고친다."""

import copy
import tkinter as tk
from tkinter import messagebox, ttk

from osint import watchlist as wl

FONT = ("Malgun Gothic", 10)
PRIO_BY_LABEL = {v: k for k, v in wl.PRIORITY_LABEL.items()}


def _join(words):
    return ", ".join(words)


class WatchlistEditor(tk.Toplevel):
    def __init__(self, master, path, on_saved=None, open_text=None):
        super().__init__(master)
        self.title("추적 대상 편집")
        self.geometry("1080x700")
        self.minsize(860, 560)
        self.path = wl.ensure_file(path)
        self.on_saved = on_saved
        self._open_text = open_text
        self.data = copy.deepcopy(wl.load(self.path))
        # 편집 창 형식으로 맞춰 둔다(고르기만 해도 '고침'으로 잡히지 않게)
        self.data["entities"] = [wl.make_entity(e["name"], [w for w in wl.keywords_of(e) if w != e["name"]],
                                                e.get("priority", "mid"), e.get("exclude", []), base=e)
                                 for e in self.data["entities"]]
        self.data["locations"] = [wl.make_location(x["name"], x.get("ko", ""), x.get("en", []) + x.get("zh", []), base=x)
                                  for x in self.data.get("locations", [])]
        self.cur_ent = None     # 편집 중인 항목 번호
        self.cur_loc = None
        self.dirty = False
        self._build()
        self._fill_entities()
        self._fill_locations()
        self.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------ 화면
    def _build(self):
        top = ttk.Frame(self, padding=(14, 10, 14, 0))
        top.pack(fill="x")
        ttk.Label(top, text="키워드를 쉼표로 구분해 넣으세요. 한글·영문·중문을 섞어 써도 자동으로 나눕니다.",
                  foreground="#444").pack(anchor="w")

        quick = ttk.LabelFrame(self, text="빠른 추가", padding=8)
        quick.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(quick, text="키워드").pack(side="left")
        self.quick_text = tk.StringVar()
        ent = ttk.Entry(quick, textvariable=self.quick_text, width=60)
        ent.pack(side="left", padx=6, fill="x", expand=True)
        ent.bind("<Return>", lambda e: self.quick_add())
        self.quick_prio = tk.StringVar(value=wl.PRIORITY_LABEL["mid"])
        ttk.Label(quick, text="중요도").pack(side="left", padx=(6, 2))
        ttk.Combobox(quick, textvariable=self.quick_prio, values=list(PRIO_BY_LABEL), state="readonly",
                     width=6).pack(side="left")
        ttk.Button(quick, text="추가", command=self.quick_add).pack(side="left", padx=6)
        ttk.Label(quick, text="예) 현대모비스, Hyundai Mobis, 现代摩比斯", foreground="#888").pack(side="left")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=14, pady=10)
        self.nb = nb
        nb.add(self._entity_tab(nb), text="기업·대상")
        nb.add(self._location_tab(nb), text="지역")

        bottom = ttk.Frame(self, padding=(14, 0, 14, 12))
        bottom.pack(fill="x")
        if self._open_text:
            ttk.Button(bottom, text="메모장으로 직접 편집", command=self._notepad).pack(side="left")
        self.status = ttk.Label(bottom, text="", foreground="#666")
        self.status.pack(side="left", padx=10)
        ttk.Button(bottom, text="닫기", command=self.close).pack(side="right")
        ttk.Button(bottom, text="저장", command=self.save).pack(side="right", padx=6)

    def _list(self, parent, cols):
        frame = ttk.Frame(parent)
        tv = ttk.Treeview(frame, columns=[c for c, _ in cols], show="headings", selectmode="browse", height=18)
        for c, w in cols:
            tv.heading(c, text=c)
            tv.column(c, width=w, anchor="w", stretch=(c == cols[0][0]))
        ys = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        return frame, tv

    def _text(self, parent, height):
        t = tk.Text(parent, height=height, wrap="word", font=FONT, relief="solid", borderwidth=1)
        t.bind("<<Modified>>", lambda e: (t.edit_modified(False), self._preview()))
        return t

    def _entity_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        left = ttk.Frame(tab)
        left.pack(side="left", fill="y")
        bar = ttk.Frame(left)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="찾기").pack(side="left")
        self.ent_filter = tk.StringVar()
        self.ent_filter.trace_add("write", lambda *_: self._fill_entities())
        ttk.Entry(bar, textvariable=self.ent_filter, width=16).pack(side="left", padx=4)
        ttk.Button(bar, text="새로", command=self.new_entity).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="삭제", command=self.delete_entity).pack(side="left", padx=4)
        frame, self.ent_list = self._list(left, [("이름", 170), ("중요도", 56), ("키워드", 56)])
        frame.pack(fill="both", expand=True)
        self.ent_list.bind("<<TreeviewSelect>>", lambda e: self._select_entity())

        form = ttk.Frame(tab, padding=(14, 0, 0, 0))
        form.pack(side="left", fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="대표 이름").grid(row=0, column=0, sticky="w", pady=3)
        self.e_name = tk.StringVar()
        ttk.Entry(form, textvariable=self.e_name).grid(row=0, column=1, sticky="we", pady=3)
        ttk.Label(form, text="중요도").grid(row=1, column=0, sticky="w", pady=3)
        prow = ttk.Frame(form)
        prow.grid(row=1, column=1, sticky="w", pady=3)
        self.e_prio = tk.StringVar(value=wl.PRIORITY_LABEL["mid"])
        cb = ttk.Combobox(prow, textvariable=self.e_prio, values=list(PRIO_BY_LABEL), state="readonly", width=6)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._preview())
        self.prio_help = ttk.Label(prow, text="", foreground="#777")
        self.prio_help.pack(side="left", padx=8)
        ttk.Label(form, text="검색 키워드").grid(row=2, column=0, sticky="nw", pady=3)
        self.e_kw = self._text(form, 7)
        self.e_kw.grid(row=2, column=1, sticky="nsew", pady=3)
        ttk.Label(form, text="제외 키워드").grid(row=3, column=0, sticky="nw", pady=3)
        self.e_ex = self._text(form, 3)
        self.e_ex.grid(row=3, column=1, sticky="nsew", pady=3)
        ttk.Label(form, text="이름이 비슷한 다른 회사(예: Hyundai Heavy)를 넣으면 그 이름이 나온 자료는 이 대상으로 잡지 않습니다.",
                  foreground="#888", wraplength=520, justify="left").grid(row=4, column=1, sticky="w")
        self.e_preview = tk.Label(form, text="", font=FONT, fg="#1d3d6e", justify="left", anchor="w", wraplength=560)
        self.e_preview.grid(row=5, column=1, sticky="w", pady=(10, 0))
        self.e_warn = tk.Label(form, text="", font=FONT, fg="#b3261e", justify="left", anchor="w", wraplength=560)
        self.e_warn.grid(row=6, column=1, sticky="w")
        form.rowconfigure(2, weight=2)
        form.rowconfigure(3, weight=1)
        self.e_name.trace_add("write", lambda *_: self._preview())
        return tab

    def _location_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        left = ttk.Frame(tab)
        left.pack(side="left", fill="y")
        bar = ttk.Frame(left)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="새로", command=self.new_location).pack(side="left")
        ttk.Button(bar, text="삭제", command=self.delete_location).pack(side="left", padx=4)
        frame, self.loc_list = self._list(left, [("지역", 200), ("키워드", 56)])
        frame.pack(fill="both", expand=True)
        self.loc_list.bind("<<TreeviewSelect>>", lambda e: self._select_location())

        form = ttk.Frame(tab, padding=(14, 0, 0, 0))
        form.pack(side="left", fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="지역 이름").grid(row=0, column=0, sticky="w", pady=3)
        self.l_name = tk.StringVar()
        ttk.Entry(form, textvariable=self.l_name).grid(row=0, column=1, sticky="we", pady=3)
        ttk.Label(form, text="국내 검색어").grid(row=1, column=0, sticky="w", pady=3)
        self.l_ko = tk.StringVar()
        ttk.Entry(form, textvariable=self.l_ko, width=20).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(form, text="국내 기사에서 쓰는 짧은 지명(예: 조지아). 국내 보도 확인 검색에 씁니다.",
                  foreground="#888").grid(row=2, column=1, sticky="w")
        ttk.Label(form, text="현지 키워드").grid(row=3, column=0, sticky="nw", pady=3)
        self.l_kw = self._text(form, 6)
        self.l_kw.grid(row=3, column=1, sticky="nsew", pady=3)
        ttk.Label(form, text="현지 지명·카운티·공장 이름(영문·중문). 같은 기업·같은 지역 자료를 묶는 데 씁니다.",
                  foreground="#888", wraplength=520, justify="left").grid(row=4, column=1, sticky="w")
        form.rowconfigure(3, weight=1)
        return tab

    # ------------------------------------------------------------ 기업·대상
    def _fill_entities(self, select=None):
        q = self.ent_filter.get().strip().lower() if hasattr(self, "ent_filter") else ""
        self.ent_list.delete(*self.ent_list.get_children())
        for i, e in enumerate(self.data["entities"]):
            if q and q not in " ".join([e["name"]] + wl.keywords_of(e)).lower():
                continue
            self.ent_list.insert("", "end", iid=str(i), values=(
                e["name"], wl.PRIORITY_LABEL.get(e.get("priority", "mid"), "보통"), len(wl.keywords_of(e))))
        if select is not None and self.ent_list.exists(str(select)):
            self.ent_list.selection_set(str(select))
            self.ent_list.see(str(select))

    def _commit_entity(self):
        """편집 칸의 내용을 목록에 반영. 바뀐 게 있으면 True."""
        i = self.cur_ent
        if i is None or i >= len(self.data["entities"]):
            return False
        old = self.data["entities"][i]
        name = self.e_name.get().strip() or old["name"]
        new = wl.make_entity(name, wl.parse_keywords(self.e_kw.get("1.0", "end")),
                             PRIO_BY_LABEL.get(self.e_prio.get(), "mid"),
                             wl.parse_keywords(self.e_ex.get("1.0", "end")), base=old)
        if new != old:
            self.data["entities"][i] = new
            self.dirty = True
            if self.ent_list.exists(str(i)):
                self.ent_list.item(str(i), values=(new["name"], wl.PRIORITY_LABEL[new["priority"]],
                                                   len(wl.keywords_of(new))))
            return True
        return False

    def _select_entity(self):
        sel = self.ent_list.selection()
        if not sel:
            return
        self._commit_entity()
        self.cur_ent = int(sel[0])
        e = self.data["entities"][self.cur_ent]
        self.e_name.set(e["name"])
        self.e_prio.set(wl.PRIORITY_LABEL.get(e.get("priority", "mid"), "보통"))
        kws = [w for w in wl.keywords_of(e) if w != e["name"]]
        self.e_kw.delete("1.0", "end")
        self.e_kw.insert("1.0", _join(kws))
        self.e_ex.delete("1.0", "end")
        self.e_ex.insert("1.0", _join(e.get("exclude", [])))
        self._preview()

    def _preview(self):
        if not hasattr(self, "e_preview") or self.cur_ent is None:
            return
        name = self.e_name.get().strip()
        prio = PRIO_BY_LABEL.get(self.e_prio.get(), "mid")
        e = wl.make_entity(name or "-", wl.parse_keywords(self.e_kw.get("1.0", "end")), prio)
        self.prio_help.configure(text=wl.PRIORITY_HELP[prio])
        self.e_preview.configure(text=f"한국어 {len(e['ko'])}개: {_join(e['ko']) or '-'}\n"
                                      f"영문 {len(e['en'])}개: {_join(e['en']) or '-'}\n"
                                      f"중문 {len(e['zh'])}개: {_join(e['zh']) or '-'}")
        self.e_warn.configure(text="\n".join(wl.warnings(e)))

    def new_entity(self):
        self._commit_entity()
        base = "새 추적 대상"
        names = {e["name"] for e in self.data["entities"]}
        name = base if base not in names else next(f"{base} {n}" for n in range(2, 999) if f"{base} {n}" not in names)
        self.data["entities"].append(wl.make_entity(name, [], "mid"))
        self.dirty = True
        self.ent_filter.set("")
        i = len(self.data["entities"]) - 1
        self.cur_ent = None
        self._fill_entities(select=i)
        self._select_entity()

    def delete_entity(self):
        if self.cur_ent is None:
            return
        name = self.data["entities"][self.cur_ent]["name"]
        if not messagebox.askyesno("추적 대상", f"'{name}'을(를) 목록에서 지울까요?", parent=self):
            return
        del self.data["entities"][self.cur_ent]
        self.cur_ent = None
        self.dirty = True
        self._fill_entities()
        self.e_name.set("")
        self.e_kw.delete("1.0", "end")
        self.e_ex.delete("1.0", "end")
        self.e_preview.configure(text="")
        self.e_warn.configure(text="")

    def quick_add(self):
        self._commit_entity()
        try:
            e, created = wl.quick_add(self.data, self.quick_text.get(), PRIO_BY_LABEL.get(self.quick_prio.get(), "mid"))
        except wl.WatchlistError as err:
            messagebox.showwarning("추적 대상", str(err), parent=self)
            return
        self.dirty = True
        self.quick_text.set("")
        self.nb.select(0)
        self.ent_filter.set("")
        i = next(n for n, x in enumerate(self.data["entities"]) if x["name"] == e["name"])
        self.cur_ent = None
        self._fill_entities(select=i)
        self._select_entity()
        self.status.configure(text=f"'{e['name']}' " + ("추가함" if created else "키워드를 보탬") + " — [저장]을 눌러야 반영됩니다")

    # ------------------------------------------------------------ 지역
    def _fill_locations(self, select=None):
        self.loc_list.delete(*self.loc_list.get_children())
        for i, loc in enumerate(self.data["locations"]):
            self.loc_list.insert("", "end", iid=str(i),
                                 values=(loc["name"], len(loc.get("en", [])) + len(loc.get("zh", []))))
        if select is not None and self.loc_list.exists(str(select)):
            self.loc_list.selection_set(str(select))

    def _commit_location(self):
        i = self.cur_loc
        if i is None or i >= len(self.data["locations"]):
            return False
        old = self.data["locations"][i]
        new = wl.make_location(self.l_name.get().strip() or old["name"], self.l_ko.get().strip(),
                               wl.parse_keywords(self.l_kw.get("1.0", "end")), base=old)
        if new != old:
            self.data["locations"][i] = new
            self.dirty = True
            if self.loc_list.exists(str(i)):
                self.loc_list.item(str(i), values=(new["name"], len(new["en"]) + len(new["zh"])))
            return True
        return False

    def _select_location(self):
        sel = self.loc_list.selection()
        if not sel:
            return
        self._commit_location()
        self.cur_loc = int(sel[0])
        loc = self.data["locations"][self.cur_loc]
        self.l_name.set(loc["name"])
        self.l_ko.set(loc.get("ko", ""))
        self.l_kw.delete("1.0", "end")
        self.l_kw.insert("1.0", _join(loc.get("en", []) + loc.get("zh", [])))

    def new_location(self):
        self._commit_location()
        names = {x["name"] for x in self.data["locations"]}
        name = next(f"새 지역 {n}" for n in range(1, 999) if f"새 지역 {n}" not in names)
        self.data["locations"].append(wl.make_location(name, "", []))
        self.dirty = True
        self.cur_loc = None
        self._fill_locations(select=len(self.data["locations"]) - 1)
        self._select_location()

    def delete_location(self):
        if self.cur_loc is None:
            return
        name = self.data["locations"][self.cur_loc]["name"]
        if not messagebox.askyesno("지역", f"'{name}'을(를) 목록에서 지울까요?", parent=self):
            return
        del self.data["locations"][self.cur_loc]
        self.cur_loc = None
        self.dirty = True
        self._fill_locations()
        self.l_name.set("")
        self.l_ko.set("")
        self.l_kw.delete("1.0", "end")

    # ------------------------------------------------------------ 저장·닫기
    def save(self):
        self._commit_entity()
        self._commit_location()
        try:
            wl.save(self.data, self.path)
        except (wl.WatchlistError, OSError) as e:
            messagebox.showerror("추적 대상", f"저장하지 못했습니다: {e}", parent=self)
            return False
        self.dirty = False
        n = len(self.data["entities"])
        self.status.configure(text=f"저장했습니다 — 추적 대상 {n}곳 · 지역 {len(self.data['locations'])}곳. 다음 레이더 실행부터 반영")
        if self.on_saved:
            self.on_saved()
        return True

    def close(self):
        self._commit_entity()
        self._commit_location()
        if self.dirty:
            ans = messagebox.askyesnocancel("추적 대상", "고친 내용을 저장할까요?", parent=self)
            if ans is None:
                return
            if ans and not self.save():
                return
        self.destroy()

    def _notepad(self):
        if self.dirty and messagebox.askyesno("추적 대상", "고친 내용을 먼저 저장할까요?", parent=self):
            if not self.save():
                return
        self._open_text(self.path)
        self.destroy()
