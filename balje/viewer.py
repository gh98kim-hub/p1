"""결과 보기 창: 마크다운 리포트를 프로그램 안에서 읽기 좋게 보여주고, 링크는 눌러서 연다."""

import re
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

FAMILY = "Malgun Gothic"

_MD_LINK = re.compile(r"\[((?:\\.|[^\]\\])+)\]\(<?(https?://[^)>\s]+)>?\)")
_URL = re.compile(r"https?://[^\s<>()\"']+[^\s<>()\"'.,;:!?]")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def parse_inline(text):
    """한 줄을 (글자, 종류, URL) 조각으로 나눈다. 종류: text / link / bold. '**'와 링크 문법은 걷어낸다."""
    out = []
    pos = 0
    pattern = re.compile(f"{_MD_LINK.pattern}|{_URL.pattern}|{_BOLD.pattern}")
    for m in pattern.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], "text", None))
        if m.group(1) is not None:          # [글자](URL)
            label = re.sub(r"\\(.)", r"\1", m.group(1))
            out.append((label, "link", m.group(2)))
        elif m.group(3) is not None:        # **굵게**
            out.append((m.group(3), "bold", None))
        else:                               # 맨 URL
            out.append((m.group(0), "link", m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], "text", None))
    return out


def line_style(line):
    """(줄 종류, 정리한 글자). 종류: h1/h2/h3/rule/skip/body."""
    s = line.rstrip()
    if re.fullmatch(r"\s*-{3,}\s*", s):
        return "rule", ""
    if re.fullmatch(r"\s*\|?[\s:|-]*-{3,}[\s:|-]*\|?\s*", s):
        return "skip", ""
    for n, tag in ((3, "h3"), (2, "h2"), (1, "h1")):
        if s.startswith("#" * n + " "):
            return tag, s[n + 1:].strip()
    if s.lstrip().startswith("|"):
        cells = [c.strip() for c in s.strip().strip("|").split("|")]
        return "body", "   ".join(cells)
    s = re.sub(r"^(\s*)- \[ \] ", r"\1☐ ", s)
    s = re.sub(r"^(\s*)- \[x\] ", r"\1☑ ", s)
    m = re.match(r"^(\s*)[-*] (.*)$", s)
    if m:
        indent = len(m.group(1))
        s = ("    " * (indent // 2)) + ("• " if indent < 2 else "◦ ") + m.group(2)
    if s.startswith("> "):
        s = s[2:]
    return "body", s


class ReportViewer(tk.Toplevel):
    def __init__(self, master, path, open_text=None, open_path=None):
        super().__init__(master)
        self.path = Path(path)
        self.title(f"결과 보기 — {self.path.name}")
        self.geometry("880x720")
        self.size = 10
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="파란 글씨를 누르면 원문이 열립니다", foreground="#666").pack(side="left")
        if open_path:
            ttk.Button(bar, text="폴더 열기", command=lambda: open_path(self.path.parent.resolve())).pack(side="right")
        if open_text:
            ttk.Button(bar, text="메모장으로 열기", command=lambda: open_text(self.path)).pack(side="right", padx=6)
        ttk.Button(bar, text="글자 −", width=6, command=lambda: self._zoom(-1)).pack(side="right")
        ttk.Button(bar, text="글자 +", width=6, command=lambda: self._zoom(1)).pack(side="right", padx=4)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="word", padx=16, pady=12, relief="flat", spacing1=2, spacing3=2,
                            cursor="arrow")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self._fonts()
        self.text.tag_configure("rule", foreground="#999")
        self.text.tag_configure("link", foreground="#1f4e8c", underline=True)
        self.text.tag_bind("link", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("link", "<Leave>", lambda e: self.text.configure(cursor="arrow"))
        self.links = {}
        self.render(self.path.read_text(encoding="utf-8"))

    def _fonts(self):
        s = self.size
        self.text.configure(font=(FAMILY, s))
        self.text.tag_configure("h1", font=(FAMILY, s + 6, "bold"), spacing1=10, spacing3=6)
        self.text.tag_configure("h2", font=(FAMILY, s + 3, "bold"), spacing1=12, spacing3=4)
        self.text.tag_configure("h3", font=(FAMILY, s + 1, "bold"), spacing1=8, spacing3=2)
        self.text.tag_configure("bold", font=(FAMILY, s, "bold"))

    def _zoom(self, d):
        self.size = max(8, min(20, self.size + d))
        self._fonts()

    def render(self, md):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        n = 0
        for line in md.splitlines():
            kind, s = line_style(line)
            if kind == "skip":
                continue
            if kind == "rule":
                t.insert("end", "─" * 60 + "\n", ("rule",))
                continue
            line_tags = (kind,) if kind in ("h1", "h2", "h3") else ()
            for piece, ptype, url in parse_inline(s):
                if ptype == "link":
                    n += 1
                    tag = f"link{n}"
                    self.links[tag] = url
                    t.insert("end", piece, line_tags + ("link", tag))
                    t.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
                elif ptype == "bold":
                    t.insert("end", piece, line_tags + ("bold",))
                else:
                    t.insert("end", piece, line_tags)
            t.insert("end", "\n")
        t.configure(state="disabled")
