"""뉴스 검색형 채널: 구글 뉴스 RSS에 사이트·지역 조건을 붙여 주정부 발표, PR 와이어, EU 경쟁총국,
현지 지방지, 업계 전문지, 중국 매체를 찾는다. 사용자가 넣은 RSS 피드도 여기서 읽는다(키 불필요)."""

import time
import urllib.parse
import xml.etree.ElementTree as ET

from balje.collect import _http_get, clean_text, fetch_google_news, normalize_link, parse_date

from .. import watchlist as wl
from ..models import Signal

LANG = {
    "en": ("en-US", "US", "US:en"),
    "zh": ("zh-CN", "CN", "CN:zh-Hans"),
}


def domain_of(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _quote(term):
    return f'"{term}"' if (" " in term or "-" in term or "&" in term) else term


def _or(terms):
    terms = [_quote(t) for t in terms if t]
    return terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"


def _chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)] or [[]]


def build_queries(channel, watch, days):
    """채널 설정 → 검색어 목록. 기업 표기·사이트·지역을 OR로 묶어 호출 수를 줄인다."""
    lang = channel.get("lang", "en")
    names = wl.search_names(watch, lang=lang, priorities=tuple(channel.get("priorities", ["high", "mid"])))
    names = names[: channel.get("max_entities", 40)]
    when = f" when:{max(1, int(days))}d"
    extra = (" " + channel["extra"]) if channel.get("extra") else ""
    queries = []
    ent_chunks = _chunks(names, channel.get("entities_per_query", 8))
    if channel.get("sites"):
        site_chunks = _chunks([f"site:{s}" for s in channel["sites"]], channel.get("sites_per_query", 6))
        for ec in ent_chunks:
            for sc in site_chunks:
                sites = sc[0] if len(sc) == 1 else "(" + " OR ".join(sc) + ")"
                queries.append(f"{_or(ec)} {sites}{extra}{when}")
    elif channel.get("by_location"):
        locs = [loc for loc in watch.get("locations", []) if loc.get(lang)]
        for ec in ent_chunks:
            for lc in _chunks(locs, channel.get("locations_per_query", 3)):
                terms = [t for loc in lc for t in loc[lang][:3]]
                queries.append(f"{_or(ec)} {_or(terms)}{extra}{when}")
    else:
        for ec in ent_chunks:
            queries.append(f"{_or(ec)}{extra}{when}")
    return queries[: channel.get("max_queries", 30)]


def search_channel(key, channel, watch, days, sleep=0.3, log=None):
    hl, gl, ceid = LANG.get(channel.get("lang", "en"), LANG["en"])
    out, seen = [], set()
    for q in build_queries(channel, watch, days):
        try:
            items = fetch_google_news(q, hl, gl, ceid)
        except Exception as e:  # noqa: BLE001 - 한 검색어 실패가 채널 전체를 막지 않게
            if log:
                log(f"[{channel.get('name', key)}] 검색 실패: {e}")
            continue
        for a in items:
            if a.link in seen:
                continue
            seen.add(a.link)
            out.append(Signal(channel=key, title=a.title, url=a.link, published=a.published,
                              source=a.press, text=a.description, lang=channel.get("lang", "en"), query=q,
                              meta={"domain": domain_of(a.source_url)} if a.source_url else {}))
        time.sleep(sleep)
    return out


# ---------------------------------------------------------------- 사용자 RSS 피드

def parse_feed(xml_bytes, key, name, lang="en"):
    root = ET.fromstring(xml_bytes)
    out = []
    atom = "{http://www.w3.org/2005/Atom}"
    for item in root.iter("item"):
        out.append(Signal(channel=key, title=clean_text(item.findtext("title")),
                          url=normalize_link(item.findtext("link")),
                          published=parse_date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")),
                          source=name, text=clean_text(item.findtext("description"))[:600], lang=lang))
    for entry in root.iter(f"{atom}entry"):
        link = entry.find(f"{atom}link")
        out.append(Signal(channel=key, title=clean_text(entry.findtext(f"{atom}title")),
                          url=normalize_link(link.get("href") if link is not None else ""),
                          published=parse_date(entry.findtext(f"{atom}updated") or entry.findtext(f"{atom}published")),
                          source=name, text=clean_text(entry.findtext(f"{atom}summary"))[:600], lang=lang))
    for s in out:
        if s.url:
            s.meta["domain"] = domain_of(s.url)
    return out


def read_feeds(feeds, key="feeds", log=None):
    out = []
    for f in feeds:
        try:
            raw, _ = _http_get(f["url"])
            out += parse_feed(raw, key, f.get("name", f["url"]), f.get("lang", "en"))
        except Exception as e:  # noqa: BLE001
            if log:
                log(f"[RSS {f.get('name', f['url'])}] 실패: {e}")
    return out
