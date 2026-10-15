"""공통 HTTP(JSON·텍스트). 표준 라이브러리만 쓴다."""

import gzip
import json
import urllib.parse
import urllib.request
import zlib

from balje.collect import _decode

USER_AGENT = "BaljeOSINT/1.0 (news research tool)"


def get(url, params=None, headers=None, timeout=20):
    if params:
        # 공백은 %20으로(NHTSA는 '+'로 쓴 공백을 거부한다)
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw)
        return raw, resp.headers.get_content_charset()


def get_json(url, params=None, headers=None, timeout=20):
    h = {"Accept": "application/json"}
    h.update(headers or {})
    raw, _ = get(url, params, h, timeout)
    return json.loads(raw.decode("utf-8"))


def get_text(url, params=None, headers=None, timeout=20):
    raw, cs = get(url, params, headers, timeout)
    return _decode(raw, cs)
