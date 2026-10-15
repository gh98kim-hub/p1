"""SEC EDGAR 전문 검색(8-K·10-Q 등 공시에 추적 대상이 언급된 문서). 키 불필요.

SEC는 자동 접속 시 User-Agent에 연락처(이메일)를 밝히라고 요구한다. 설정의 'SEC 연락처 이메일'을 쓴다.
"""

import re

from balje.collect import extract_body, parse_date

from .. import http
from ..models import Signal

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"


def headers(email):
    """SEC 안내 형식: '이름 연락처이메일' + gzip 허용."""
    return {"User-Agent": f"Balje OSINT {email or 'contact-email-not-set'}", "Accept-Encoding": "gzip, deflate"}


def parse_fts(data, query=""):
    out = []
    for hit in (data.get("hits") or {}).get("hits", []):
        src = hit.get("_source") or {}
        adsh = src.get("adsh") or ""
        ciks = src.get("ciks") or []
        filename = (hit.get("_id") or "").split(":", 1)[-1]
        if not (adsh and ciks and filename):
            continue
        cik = str(int(ciks[0]))
        url = f"{ARCHIVE}/{cik}/{adsh.replace('-', '')}/{filename}"
        company = re.sub(r"\s+\(CIK \d+\)", "", (src.get("display_names") or ["?"])[0]).strip()
        company = re.sub(r"\s{2,}", " ", company)
        form = src.get("form") or src.get("root_form") or ""
        ftype = src.get("file_type") or ""
        desc = src.get("file_description") or ""
        title = f"[{form}] {company}" + (f" · {ftype}" if ftype and ftype != form else "") + (f" · {desc}" if desc else "")
        out.append(Signal(
            channel="sec", title=title, url=url, published=parse_date(src.get("file_date")),
            source=f"SEC EDGAR ({company})", query=query,
            text=" / ".join(x for x in [", ".join(src.get("biz_locations") or []), src.get("period_ending") or ""] if x),
            meta={"uid": f"{adsh}:{filename}", "form": form, "adsh": adsh, "cik": cik, "company": company,
                  "index": f"{ARCHIVE}/{cik}/{adsh.replace('-', '')}/{adsh}-index.htm",
                  "biz_locations": src.get("biz_locations") or []},
        ))
    return out


def search(query, start, end, forms, email=""):
    params = {"q": query, "dateRange": "custom", "startdt": start.strftime("%Y-%m-%d"),
              "enddt": end.strftime("%Y-%m-%d")}
    if forms:
        params["forms"] = forms
    data = http.get_json(FTS_URL, params, headers(email))
    return parse_fts(data, query)


def document_text(url, email="", max_chars=4000):
    """공시 원문 일부(발제문 근거용)."""
    html_text = http.get_text(url, headers=headers(email))
    text = extract_body(html_text, max_chars)
    if not text:
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;|&#160;", " ", text)
        text = " ".join(text.split())[:max_chars]
    return text
