"""미국 법원: CourtListener 검색 API(v4). PACER 문서를 모은 무료 공개 DB(RECAP)와 판결문을 검색한다.

토큰은 설정의 'CourtListener 토큰'에 넣는다(공개 저장소에 올리지 않는다).
"""

import re

from balje.collect import clean_text, parse_date

from .. import http
from ..models import Signal

SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
SITE = "https://www.courtlistener.com"


def _abs(url):
    if not url:
        return ""
    return url if url.startswith("http") else SITE + url


def parse_results(data, kind, query=""):
    out = []
    for r in data.get("results", []):
        case = clean_text(r.get("caseName") or r.get("case_name") or "")
        court = r.get("court") or r.get("court_citation_string") or r.get("court_id") or ""
        docket = r.get("docketNumber") or r.get("docket_number") or ""
        snippet, link = "", ""
        if kind == "r":
            docs = r.get("recap_documents") or []
            if docs:
                d0 = docs[0]
                snippet = clean_text(d0.get("snippet") or d0.get("description") or "")
            link = _abs(r.get("docket_absolute_url") or r.get("absolute_url"))
            extra = " · ".join(x for x in [r.get("suitNature") or "", r.get("cause") or ""] if x)
        else:
            ops = r.get("opinions") or []
            if ops:
                snippet = clean_text(ops[0].get("snippet") or "")
            link = _abs(r.get("absolute_url"))
            extra = r.get("status") or ""
        snippet = re.sub(r"\s+", " ", snippet)
        label = "소송 기록" if kind == "r" else "판결문"
        out.append(Signal(
            channel="courts", title=f"[{label}] {case} ({court})", url=link,
            published=parse_date(r.get("dateFiled") or r.get("date_filed")),
            source=f"CourtListener · {court}", query=query,
            text=" / ".join(x for x in [f"사건번호 {docket}" if docket else "", extra, snippet] if x),
            meta={"uid": f"cl:{kind}:{r.get('docket_id') or r.get('cluster_id') or link}",
                  "kind": kind, "court": court, "docket": docket, "case": case},
        ))
    return out


def search(query, token, since, kind="r"):
    """kind: r=소송 기록(RECAP), o=판결문."""
    params = {"q": query, "type": kind, "order_by": "dateFiled desc",
              "filed_after": since.strftime("%m/%d/%Y")}
    h = {"Authorization": f"Token {token}"} if token else {}
    return parse_results(http.get_json(SEARCH_URL, params, h), kind, query)
