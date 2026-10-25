"""김하늘 전용 편집툴(exe판): 저장소, 로컬 서버, Claude 연결."""

import json
import urllib.request
from urllib.error import HTTPError

import pytest

from haneul import server
from haneul.config import load_config
from haneul.store import Store, StoreError


@pytest.fixture
def app(tmp_path):
    a = server.App(tmp_path / "data.json", lambda: {"ai": {}}, 0).start()
    yield a
    a.stop()


def post(url, path, body, header=True, host=None):
    headers = {"Content-Type": "application/json"}
    if header:
        headers["X-Haneul"] = "1"
    if host:
        headers["Host"] = host
    req = urllib.request.Request(url + path.lstrip("/"), data=json.dumps(body).encode("utf-8"),
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def test_store_roundtrip_and_order(tmp_path):
    st = Store(tmp_path / "d.json")
    st.set("examples/b", {"title": "나", "addedAt": 1})
    st.set("examples/a", {"title": "가", "addedAt": 3})
    st.set("examples/c", {"title": "다"})
    assert [d["id"] for d in st.list("examples", "addedAt", "desc")] == ["a", "b", "c"]
    assert [d["id"] for d in st.list("examples")] == ["a", "b", "c"]
    assert len(st.list("examples", limit=2)) == 2
    st.update("examples/a", {"sub": "부제"})
    assert st.get("examples/a") == {"title": "가", "addedAt": 3, "sub": "부제"}
    st.delete("examples/b")
    st.flush()
    again = Store(tmp_path / "d.json")
    assert sorted(d["id"] for d in again.list("examples")) == ["a", "c"]


def test_store_rejects_bad_paths(tmp_path):
    st = Store(tmp_path / "d.json")
    for bad in ("examples", "a/b/c", "../x", "examples/a b"):
        with pytest.raises(StoreError):
            st.set(bad, {})
    with pytest.raises(StoreError):
        st.update("config/main", {"x": 1})  # 없는 문서


def test_broken_file_is_kept_aside(tmp_path):
    f = tmp_path / "d.json"
    f.write_text("{not json", encoding="utf-8")
    st = Store(f)
    assert st.list("examples") == []
    assert (tmp_path / "d.broken.json").exists()


def test_page_has_shim_before_page_script(app):
    with urllib.request.urlopen(app.url, timeout=10) as r:
        html = r.read().decode("utf-8")
    assert html.index("window.claude = Object.freeze") < html.index("김하늘 전용 편집툴")
    assert html.startswith("<!doctype html>")


def test_db_routes(app):
    post(app.url, "/api/db/set", {"path": "config/main", "data": {"rows": 2, "per": 14}})
    assert post(app.url, "/api/db/get", {"path": "config/main"})["data"] == {"rows": 2, "per": 14}
    assert post(app.url, "/api/db/get", {"path": "config/none"})["data"] is None
    err = post(app.url, "/api/db/set", {"path": "bad", "data": {}})["error"]
    assert err["code"] == "invalid_argument"


def test_requests_without_header_or_from_other_host_are_refused(app):
    with pytest.raises(HTTPError) as e:
        post(app.url, "/api/db/list", {"collection": "examples"}, header=False)
    assert e.value.code == 403
    with pytest.raises(HTTPError) as e:
        post(app.url, "/api/db/list", {"collection": "examples"}, host="evil.example:47321")
    assert e.value.code == 403


def test_sample_passes_prompt_and_reports_failures(app, monkeypatch):
    seen = {}

    def fake(system, user, config):
        seen.update(system=system, user=user)
        return '{"candidates": []}'

    monkeypatch.setattr(server.llm, "call_claude", fake)
    out = post(app.url, "/api/sample", {"prompt": "기사", "json": True})
    assert out == {"text": '{"candidates": []}'}
    assert seen["user"] == "기사" and "JSON" in seen["system"]

    monkeypatch.setattr(server.llm, "call_claude", lambda *a: "> Claude 구독 실패: Claude Code 로그인이 필요합니다.")
    err = post(app.url, "/api/sample", {"prompt": "기사"})["error"]
    assert err["detail"] == "Claude 구독 실패: Claude Code 로그인이 필요합니다."


def test_config_defaults_and_merge(tmp_path):
    f = tmp_path / "c.json"
    assert load_config(f)["claude_auth"] == "subscription"
    f.write_text(json.dumps({"claude_auth": "api", "anthropic_api_key": "k", "ai": {"effort": "high"}}), encoding="utf-8")
    cfg = load_config(f)
    assert cfg["claude_auth"] == "api" and cfg["ai"] == {"model": "claude-opus-5-5", "effort": "high"}
