"""출처 분류·정부 채널·결과 화면(대시보드) 시험."""

import os

import pytest

from balje import board as bmod
from osint import classify, http, radar, reverse
from osint.models import Signal
from osint.sources import federal_register as fr
from osint.sources import news

from test_osint import FIX, NOW, _config, _json, _watch, fake_net  # noqa: F401 - pytest 픽스처 재사용
from test_balje import _run_full


def test_classify_domains():
    assert classify.domain_kind("www.georgia.org") == "gov"
    assert classify.domain_kind("gov.georgia.gov") == "gov"
    assert classify.domain_kind("miit.gov.cn") == "gov"
    assert classify.domain_kind("korea.kr") == "gov"
    assert classify.domain_kind("ec.europa.eu") == "gov"
    assert classify.domain_kind("prnewswire.com") == "corp"
    assert classify.domain_kind("reuters.com") is None
    assert classify.domain_kind("notgov.com") is None
    assert classify.kind_of(Signal(channel="local_media", title="t", url="u", meta={"domain": "governor.ky.gov"})) == "gov"
    assert classify.kind_of(Signal(channel="local_media", title="t", url="u")) == "media"
    assert classify.kind_of(Signal(channel="pr_wire", title="t", url="u")) == "corp"
    assert classify.kind_of(Signal(channel="nhtsa", title="t", url="u")) == "gov"


def test_google_news_keeps_source_site(fake_net):
    sigs = news.search_channel("gov_press", {"sites": ["a.gov"]}, _watch(), 7, sleep=0)
    assert sigs and sigs[0].meta["domain"] == "gov.example"


def test_search_topics_uses_sites_and_korean_edition(monkeypatch):
    from balje import collect
    seen = []

    def fake(q, hl="en-US", gl="US", ceid="US:en"):
        seen.append((q, hl, ceid))
        return collect.parse_google_news((FIX / "gov_press.xml").read_bytes(), q)

    monkeypatch.setattr(news, "fetch_google_news", fake)
    ch = {"name": "한국 정부", "lang": "ko", "sites": ["korea.kr", "molit.go.kr"], "terms": ["자동차", "자율주행", "리콜"],
          "terms_per_query": 2}
    sigs = news.search_topics("kr_gov", ch, 7, sleep=0)
    assert seen[0] == ("(자동차 OR 자율주행) (site:korea.kr OR site:molit.go.kr) when:7d", "ko", "KR:ko")
    assert len(seen) == 2 and len(sigs) == 2               # 같은 링크는 한 번만
    assert sigs[0].channel == "kr_gov" and sigs[0].meta["domain"] == "gov.example"


def test_read_feeds_all_failed_is_an_error(monkeypatch):
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    monkeypatch.setattr(news, "_http_get", boom)
    with pytest.raises(RuntimeError, match="404"):
        news.read_feeds([{"name": "가", "url": "https://x.example/a.xml"}], "kr_gov")
    assert news.read_feeds([], "feeds") == []


def test_federal_register_parse():
    sigs = fr.parse(_json("fed_register.json"), "q")
    assert [s.channel for s in sigs] == ["fed_register", "fed_register"]
    assert sigs[0].source == "미 연방관보 · International Trade Administration"
    assert sigs[0].meta["doc_type"] == "고시" and sigs[1].meta["doc_type"] == "규정안"
    assert sigs[1].text == "proposed standard"          # 초록이 없으면 발췌(태그 제거)
    assert sigs[0].published.date().isoformat() == "2026-10-12"


def _gov_config(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    chs = cfg["osint"]["channels"]
    chs["fed_register"].update(enabled=True, topics=["batteries"])
    chs["kr_gov"].update(enabled=True, sites=[], feeds=[{"name": "가상부", "url": "https://kr.example/rss.xml"}])
    orig = http.get_json
    terms = []

    def fake(url, params=None, headers=None, timeout=20):
        if "federalregister" in url:
            term = dict(params)["conditions[term]"]
            terms.append(term)
            data = _json("fed_register.json")
            if term == '"Bolt Cells"':
                return {"results": data["results"][:1]}
            return data if term == "batteries" else {"results": []}
        return orig(url, params, headers, timeout)

    monkeypatch.setattr(http, "get_json", fake)
    monkeypatch.setattr(news, "_http_get", lambda url: ((FIX / "kr_gov.xml").read_bytes(), "utf-8"))
    return cfg, terms


def test_radar_government_channels_and_board(tmp_path, fake_net, monkeypatch):
    cfg, terms = _gov_config(tmp_path, monkeypatch)
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    st = res["status"]
    assert '"Bolt Cells"' in terms and "batteries" in terms
    assert st["fed_register"]["count"] == 2 and st["kr_gov"]["count"] == 1   # 농산물 보도자료는 빠짐
    by_ch = {}
    for s in res["signals"]:
        by_ch.setdefault(s.channel, []).append(s)
    # 기업명이 없어도 정책 주제로 잡힌 연방관보 문서·정부 보도자료는 보인다
    topic = [s for s in by_ch["fed_register"] if s.meta.get("topic") == "batteries"]
    assert topic and not topic[0].entities
    assert by_ch["kr_gov"][0].title.startswith("가상부, 전기차")
    assert by_ch["fed_register"][0].entities or by_ch["fed_register"][1].entities

    data = bmod.load(res["json"])
    keys = [g["key"] for g in data["groups"]]
    for k in ("cand", "new", "all", "gov", "corp", "media", "gov/sec", "gov/fed_register", "gov/kr_gov",
              "gov/nhtsa", "gov/courts", "gov/gov_press", "media/local_media", "status"):
        assert k in keys, k
    gov = bmod.rows_in(data, "gov")
    assert {r["values"][1] for r in gov} >= {"SEC 공시", "미국 법원", "NHTSA 리콜", "미 연방관보", "한국 정부 보도자료",
                                            "주정부·지자체 발표"}
    assert len(bmod.rows_in(data, "all")) == len(res["signals"])
    # 표에는 주소를 글자로 늘어놓지 않는다(주소는 버튼으로 연다)
    for r in data["rows"]:
        assert not any("http" in str(v) for v in r["values"]), r["values"]
    sig_rows = [r for r in data["rows"] if "all" in r["groups"]]
    assert all(r["url"] and any(b["t"] == "link" and b["url"] == r["url"] for b in r["detail"]) for r in sig_rows)
    cands = bmod.rows_in(data, "cand")
    assert cands and cands[0]["values"][0] == "C1"
    assert any(b["t"] == "checks" for b in cands[0]["detail"])
    assert sum(1 for b in cands[0]["detail"] if b["t"] == "link") >= 2
    status = {r["id"]: r for r in bmod.rows_in(data, "status")}
    assert status["status-fed_register"]["values"][2] == 2
    assert data["files"]["md"] == res["md"].name


def test_radar_board_marks_failed_channel(tmp_path, fake_net, monkeypatch):
    cfg = _config(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("SEC가 접속을 거부했습니다(403).")

    monkeypatch.setattr(radar.sec_edgar, "search", boom)
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    data = bmod.load(res["json"])
    g = {x["key"]: x for x in data["groups"]}
    assert g["gov/sec"]["label"].endswith("⚠")
    assert any("수집 실패: SEC 공시" in line for line in data["summary"])
    row = [r for r in data["rows"] if r["id"] == "status-sec"][0]
    assert row["values"][-1].startswith("오류:")


def test_radar_translates_all_signals_up_to_limit(tmp_path, fake_net, monkeypatch):
    from balje import translate as tmod
    seen = []

    def fake(system, user, config):
        import json
        items = json.loads(user[user.index("["):])
        seen.extend(it["id"] for it in items)
        return json.dumps({it["id"]: {"title": "번역 " + it["title"][:10], "summary": ""} for it in items})

    monkeypatch.setattr(tmod, "available_provider", lambda config: "claude")
    monkeypatch.setitem(tmod.PROVIDERS, "claude", ("Claude", fake))
    cfg = _config(tmp_path)
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    # 후보에 안 든 자료도 번역해 목록에 한국어로 보인다
    assert all(s.meta.get("ko_title") for s in res["signals"])
    (tmp_path / "b").mkdir()
    cfg2 = _config(tmp_path / "b")
    cfg2["osint"]["translate_max"] = 2
    seen.clear()
    res2 = radar.run(cfg2, log=lambda m: None, out_dir=tmp_path / "out2", now=NOW)
    assert len(seen) == 2
    cand_uids = [s.uid for c in res2["cands"] for s in c.signals]
    assert seen == list(dict.fromkeys(cand_uids))[:2]        # 후보 근거 자료부터


def test_reverse_board(tmp_path, fake_net):
    cfg = _config(tmp_path)
    res = reverse.run("가상차가 오크카운티 공장을 늘린다.", cfg, log=lambda m: None, use_ai=False,
                      out_dir=tmp_path / "out", now=NOW)
    data = bmod.load(res["json"])
    assert data["kind"] == "reverse"
    assert bmod.rows_in(data, "ai")[0]["id"] == "ai-none"
    assert len(bmod.rows_in(data, "src")) == len(res["sources"])
    assert bmod.rows_in(data, "article")[0]["detail"][-1]["x"].startswith("가상차가")


def test_notes_board(tmp_path, monkeypatch):
    res, _ = _run_full(tmp_path, monkeypatch)
    data = bmod.load(res["json"])
    assert data["kind"] == "notes" and data["files"]["md"] == res["md"].name
    keys = [g["key"] for g in data["groups"]]
    assert keys[:3] == ["cand", "ai", "release"] and "all" in keys and "foreign" in keys
    assert len(bmod.rows_in(data, "all")) == len(res["clusters"])
    assert bmod.rows_in(data, "foreign")
    row = bmod.rows_in(data, "cand")[0]
    kinds = [b["t"] for b in row["detail"]]
    assert kinds[0] == "title" and "checks" in kinds and "link" in kinds
    assert not any("http" in str(v) for r in data["rows"] for v in r["values"])
    assert "**" not in str(data)


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        pytest.skip("화면 없음")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("화면 없음")
    root.withdraw()
    yield root
    root.destroy()


def test_dashboard_window(tmp_path, fake_net, monkeypatch, tk_root):
    from balje.dashboard import Dashboard
    cfg, _ = _gov_config(tmp_path, monkeypatch)
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    data = bmod.load(res["json"])
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    d = Dashboard(tk_root, data, res["json"])
    d.update()
    assert d.current_group == "cand"                       # 후보가 있으면 후보부터
    assert len(d.table.get_children()) == len(bmod.rows_in(data, "cand"))
    assert d._widgets                                      # 상세의 [원문 열기] 버튼
    d._widgets[0].invoke()
    assert opened and opened[0].startswith("https://")
    d.side.selection_set("gov/fed_register")
    d.update()
    d._on_group()
    assert len(d.table.get_children()) == 2
    assert d.table.heading("c3")["text"] == "제목(번역)"
    d.search.set("Fictional Motor")
    d.update()
    assert len(d.table.get_children()) == 1
    d._sort("c0")
    d._zoom(2)
    d.search.set("")
    d.side.selection_set("status")
    d._on_group()
    assert d.table.get_children()
    d.destroy()


# ---------------------------------------------------------------- [AI 번역] 버튼

def test_detail_texts_round_trip():
    detail = [bmod.title("Acme Motors expands Oak County plant"), bmod.kv([("출처", "Testland Governor office")]),
              bmod.bullets(["first point here", "둘째"]), bmod.link("Original press release title", "https://x"),
              bmod.h("요약"), dict(bmod.sub("원문 제목: Original"), keep=True)]
    texts = bmod.detail_texts(detail)
    assert texts == {"0": "Acme Motors expands Oak County plant", "1.0": "Testland Governor office",
                     "2.0": "first point here", "2.1": "둘째", "3": "Original press release title", "4": "요약"}
    new = bmod.apply_texts(detail, {"0": "가상차, 공장 확장", "1.0": "테스트랜드 주지사실", "2.0": "첫째", "3": "원 보도자료"})
    assert new[0]["x"] == "가상차, 공장 확장" and new[1]["x"] == [["출처", "테스트랜드 주지사실"]]
    assert new[2]["x"] == ["첫째", "둘째"] and new[3]["x"] == "원 보도자료" and new[3]["url"] == "https://x"
    assert detail[0]["x"].startswith("Acme")                 # 원본은 그대로


def test_translate_texts(monkeypatch):
    import json
    from balje import translate as tmod
    calls = []

    def fake(system, user, config):
        calls.append(config["ai"]["effort"])
        items = json.loads(user[user.index("{"):])
        return json.dumps({k: "번역:" + v[:8] for k, v in items.items()})

    monkeypatch.setattr(tmod, "available_provider", lambda c: "claude")
    monkeypatch.setitem(tmod.PROVIDERS, "claude", ("Claude", fake))
    out = tmod.translate_texts({"a": "Hyundai expands its Georgia plant", "b": "현대차 공장", "c": "https://x.com/a-b-c-d",
                                "d": "现代汽车本土销量"}, {"ai": {}}, log=lambda m: None)
    assert set(out) == {"a", "d"} and calls == ["low"]        # 한국어·주소만 있는 글은 보내지 않는다
    big = {str(i): "word " * 400 for i in range(5)}
    tmod.translate_texts(big, {"ai": {}}, log=lambda m: None, max_chars=4500)
    assert len(calls) == 1 + 3                                 # 길면 나눠 보낸다
    monkeypatch.setitem(tmod.PROVIDERS, "claude", ("Claude", lambda s, u, c: "> Claude 구독 실패: 로그인이 필요합니다"))
    with pytest.raises(RuntimeError, match="로그인이 필요합니다"):
        tmod.translate_texts({"a": "Hyundai expands its Georgia plant"}, {"ai": {}}, log=lambda m: None)
    monkeypatch.setattr(tmod, "available_provider", lambda c: None)
    with pytest.raises(RuntimeError, match="구독 로그인"):
        tmod.translate_texts({"a": "Hyundai expands its Georgia plant"}, {"ai": {}}, log=lambda m: None)
    assert tmod.translate_texts({"a": "한국어만"}, {"ai": {}}) == {}


def _wait(d):
    import time
    end = time.monotonic() + 5            # fake_net이 time.sleep을 바꿔 두므로 시각으로 잰다
    while time.monotonic() < end:
        d.update()
        if not d._busy:
            return
    raise AssertionError("번역이 끝나지 않음")


def test_dashboard_translate_buttons(tmp_path, fake_net, monkeypatch, tk_root):
    from balje import translate as tmod
    from balje.dashboard import Dashboard
    sent = []

    def fake_tr(texts, config, log=print, max_chars=8000):
        sent.append(dict(texts))
        return {k: "번역 " + v[:12] for k, v in texts.items() if tmod.has_foreign(v)}

    monkeypatch.setattr(tmod, "translate_texts", fake_tr)
    monkeypatch.setattr("balje.dashboard._ai_label", lambda cfg: "Claude")
    cfg = _config(tmp_path)
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    data = bmod.load(res["json"])
    d = Dashboard(tk_root, data, res["json"], translate_config=lambda: cfg)
    d.side.selection_set("all")
    d._on_group()
    d.update()
    row = d.current_row
    d.tr_btn.invoke()
    _wait(d)
    assert "row_title" in sent[0] and "0" in sent[0]          # 목록 제목 + 상세 제목
    assert row["tr"]["title"].startswith("번역 ")
    assert d.table.item(row["id"])["values"][3].startswith("번역 ")
    body = d.text.get("1.0", "end")
    assert "AI 번역본(Claude)" in body and row["tr"]["detail"][0]["x"] in body
    assert d.orig_btn.winfo_manager() == "pack"
    d.orig_btn.invoke()
    assert row["detail"][0]["x"] in d.text.get("1.0", "end") and "AI 번역본" not in d.text.get("1.0", "end")
    # 번역은 결과 파일에 남는다
    again = bmod.load(res["json"])
    assert [r for r in again["rows"] if r["id"] == row["id"]][0]["tr"]["title"] == row["tr"]["title"]
    # 목록 제목 한꺼번에
    sent.clear()
    d.list_tr_btn.invoke()
    _wait(d)
    assert row["id"] not in sent[0]                          # 이미 번역한 행은 다시 보내지 않는다
    assert all(str(d.table.item(i)["values"][3]).startswith("번역 ") or not tmod.has_foreign(
        str(d.table.item(i)["values"][3])) for i in d.table.get_children())
    d.destroy()


def test_dashboard_translate_error_shows_message(tmp_path, fake_net, monkeypatch, tk_root):
    from balje import translate as tmod
    from balje.dashboard import Dashboard
    shown = []

    def boom(texts, config, log=print, max_chars=8000):
        raise RuntimeError(tmod.NO_AI)

    monkeypatch.setattr(tmod, "translate_texts", boom)
    monkeypatch.setattr("tkinter.messagebox.showwarning", lambda title, msg, parent=None: shown.append(msg))
    cfg = _config(tmp_path)
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    d = Dashboard(tk_root, bmod.load(res["json"]), res["json"], translate_config=lambda: cfg)
    d.update()
    d.tr_btn.invoke()
    _wait(d)
    assert shown == [tmod.NO_AI] and str(d.tr_btn["state"]) == "normal"
    d.destroy()


def test_dashboard_without_translator_hides_buttons(tmp_path, fake_net, tk_root):
    from balje.dashboard import Dashboard
    res = radar.run(_config(tmp_path), log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    d = Dashboard(tk_root, bmod.load(res["json"]), res["json"])
    d.update()
    assert not d.tr_btn.winfo_ismapped() and not hasattr(d, "list_tr_btn")
    d.destroy()
