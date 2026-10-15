"""미국 연방관보(Federal Register) API. 키 없이 쓴다.

NHTSA 규정·리콜 관련 고시, 상무부·ITC 반덤핑·상계관세(배터리·타이어 등), EPA·재무부(IRA) 규정이
여기에 원문으로 실린다. https://www.federalregister.gov/developers/documentation/api/v1
"""

from balje.collect import clean_text, parse_date

from .. import http
from ..models import Signal

API_URL = "https://www.federalregister.gov/api/v1/documents.json"
FIELDS = ["title", "abstract", "html_url", "publication_date", "agencies", "type", "document_number", "excerpts"]
TYPE_KO = {"Rule": "규정", "Proposed Rule": "규정안", "Notice": "고시", "Presidential Document": "대통령 문서"}


def parse(data, query=""):
    out = []
    for r in (data or {}).get("results") or []:
        num = r.get("document_number") or ""
        url = r.get("html_url") or ""
        if not (num or url):
            continue
        agencies = [a.get("name") or a.get("raw_name") or "" for a in (r.get("agencies") or [])]
        agencies = [a for a in agencies if a]
        dtype = r.get("type") or ""
        text = clean_text(r.get("abstract") or "") or clean_text(r.get("excerpts") or "")
        out.append(Signal(
            channel="fed_register",
            title=clean_text(r.get("title") or ""),
            url=url, published=parse_date(r.get("publication_date")),
            source="미 연방관보" + (f" · {agencies[0]}" if agencies else ""),
            text=text[:1500], query=query,
            meta={"uid": f"fr:{num or url}", "agencies": agencies, "doc_type": TYPE_KO.get(dtype, dtype),
                  "document_number": num, "domain": "federalregister.gov"},
        ))
    return out


def search(term, since, per_page=20):
    params = [("conditions[term]", term), ("conditions[publication_date][gte]", since.strftime("%Y-%m-%d")),
              ("order", "newest"), ("per_page", str(per_page))]
    params += [("fields[]", f) for f in FIELDS]
    return parse(http.get_json(API_URL, params), term)
