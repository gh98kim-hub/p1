"""공통 HTTP(JSON·텍스트). 표준 라이브러리만 쓴다."""

import json
import urllib.parse
import urllib.request

from balje.collect import USER_AGENT, _decode


def get(url, params=None, headers=None, timeout=20):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get_content_charset()


def get_json(url, params=None, headers=None, timeout=20):
    raw, _ = get(url, params, headers, timeout)
    return json.loads(raw.decode("utf-8"))


def get_text(url, params=None, headers=None, timeout=20):
    raw, cs = get(url, params, headers, timeout)
    return _decode(raw, cs)
