"""OSINT 데스크 테스트. 네트워크는 모두 가짜로 바꾸고, 추적 대상은 가상 목록(tests/fixtures/osint)을 쓴다."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from balje import collect
from balje.config import _merge, load_config
from osint import candidates, domestic, http, prompts, radar, report, reverse
from osint import watchlist as wl
from osint.models import Signal
from osint.sources import courts, news, nhtsa, sec_edgar
from osint.store import Store

FIX = Path(__file__).resolve().parent / "fixtures" / "osint"
NOW = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)


def _watch():
    return wl.load(FIX / "watchlist.json")


def _json(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 추적 대상

def test_default_watchlist_is_valid_and_rich():
    w = wl.load()
    assert len(w["entities"]) >= 50 and len(w["locations"]) >= 20
    names = {e["name"] for e in w["entities"]}
    assert {"현대자동차", "기아", "LG에너지솔루션", "삼성SDI", "SK온", "현대모비스"} <= names
    assert {e["priority"] for e in w["entities"]} == {"high", "mid", "low"}


def test_watchlist_matching_and_excludes():
    w = wl.load()
    assert "현대자동차" in wl.match_entities("Hyundai Motor Group Metaplant America in Ellabell", w)
    # 다른 현대 계열사만 나오면 현대자동차로 잡지 않는다
    hits = wl.match_entities("HD Hyundai Heavy Industries wins order", w)
    assert "현대자동차" not in hits
    assert "기아" not in wl.match_entities("Nokia earnings", w)
    assert "조지아 브라이언카운티(HMGMA)" in wl.match_locations("plant in Bryan County, Georgia", w)


def test_watchlist_error_message(tmp_path):
    bad = tmp_path / "watchlist.json"
    bad.write_text('{"entities": [ {"name": "x",} ]}', encoding="utf-8")
    with pytest.raises(wl.WatchlistError, match="번째 줄"):
        wl.load(bad)


def test_ensure_file_copies_default(tmp_path):
    p = wl.ensure_file(tmp_path / "w.json")
    assert p.exists() and wl.load(p)["entities"]


# ---------------------------------------------------------------- 수집기 파서

def test_sec_parse():
    sigs = sec_edgar.parse_fts(_json("sec_fts.json"), '"Globex"')
    assert len(sigs) == 1
    s = sigs[0]
    assert s.url == "https://www.sec.gov/Archives/edgar/data/123456/000012345626000077/globex-ex99_1.htm"
    assert s.title.startswith("[8-K] Globex Corp (GBX)") and s.published.day == 12
    assert s.meta["company"] == "Globex Corp (GBX)" and "Riverton" in s.text
    assert "contact-email-not-set" in sec_edgar.headers("")["User-Agent"]
    assert "me@example.com" in sec_edgar.headers("me@example.com")["User-Agent"]


def test_courts_parse():
    r = courts.parse_results(_json("courts_r.json"), "r")[0]
    assert r.url == "https://www.courtlistener.com/docket/555/doe-v-acme-motors-america-inc/"
    assert "소송 기록" in r.title and "3:26-cv-01234" in r.text and "battery" in r.text
    o = courts.parse_results(_json("courts_o.json"), "o")[0]
    assert "판결문" in o.title and o.url.endswith("/opinion/777/bolt-cells-v-globex/")


def test_courts_sends_token(monkeypatch):
    seen = {}

    def fake(url, params=None, headers=None, timeout=20):
        seen.update(params=params, headers=headers)
        return _json("courts_r.json")

    monkeypatch.setattr(http, "get_json", fake)
    courts.search('"Acme Motors"', "TOKEN123", NOW, "r")
    assert seen["headers"] == {"Authorization": "Token TOKEN123"}
    assert seen["params"]["filed_after"] == "10/14/2026" and seen["params"]["type"] == "r"


def test_nhtsa_dates_and_merge():
    assert nhtsa.parse_report_date("13/10/2026").month == 10
    assert nhtsa.parse_report_date("10/13/2026").day == 13
    assert nhtsa.parse_report_date("2026-10-13T00:00:00").day == 13
    rows = _json("nhtsa_recalls.json")["results"]
    rows2 = [dict(rows[0], Model="VAN")]
    sigs = nhtsa.collect_recalls(rows + rows2, datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert len(sigs) == 1  # 오래된 리콜은 빠지고, 같은 캠페인은 합쳐진다
    assert sigs[0].meta["vehicles"] == ["2026 ACME ROADSTER", "2026 ACME VAN"]
    assert sigs[0].url.endswith("nhtsaId=26V700000")


def test_news_query_builder():
    w = _watch()
    ch = {"sites": ["a.gov", "b.gov"], "extra": "(merger OR antitrust)"}
    qs = news.build_queries(ch, w, 7)
    assert qs == ['("Acme Motors" OR "Bolt Cells") (site:a.gov OR site:b.gov) (merger OR antitrust) when:7d']
    loc = news.build_queries({"by_location": True, "priorities": ["high"]}, w, 3)
    assert loc == ['("Acme Motors" OR "Bolt Cells") ("Oak County" OR Riverton) when:3d']
    zh = news.build_queries({"lang": "zh"}, w, 7)
    assert zh == ["艾克米汽车 when:7d"]


def test_feed_parse_atom_and_rss():
    atom = news.parse_feed((FIX / "feed_atom.xml").read_bytes(), "feeds", "Bolt")
    assert atom[0].title == "Bolt Cells signs supply deal" and atom[0].url == "https://bolt.example/news/1"
    rss = news.parse_feed((FIX / "local.xml").read_bytes(), "feeds", "Riverton")
    assert rss[0].published.day == 13


# ---------------------------------------------------------------- 저장소·후보

def _sig(channel, title, entities, locations=(), day=13, **meta):
    return Signal(channel=channel, title=title, url=f"https://x.example/{channel}/{title}",
                  published=datetime(2026, 10, day, tzinfo=timezone.utc), source=channel,
                  entities=list(entities), locations=list(locations), meta=meta)


def test_store_new_then_seen(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    a = _sig("sec", "A", ["가상자동차"])
    st.upsert([a], NOW)
    assert a.is_new
    b = _sig("sec", "A", ["가상자동차"])
    st.upsert([b], NOW)
    assert not b.is_new and b.first_seen == NOW
    assert [s.title for s in st.recent(14, NOW)] == ["A"]
    st.set("k", "v")
    assert st.get("k") == "v"
    st.close()


def test_candidates_mosaic_and_single():
    w = _watch()
    chs = load_config("없음.json")["osint"]["channels"]
    old = _sig("gov_press", "gov", ["가상자동차"], ["테스트주 오크카운티"], day=5)
    old.is_new = False
    cur = [_sig("local_media", "jobs", ["가상자동차"], ["테스트주 오크카운티"]),
           _sig("courts", "suit", ["볼트셀"]),
           _sig("trade_media", "ctx", ["글로벡스"])]          # low 우선순위만 → 후보 아님
    cands = candidates.build(cur, [old], w, chs)
    kinds = {(c.kind, c.entity) for c in cands}
    assert ("mosaic", "가상자동차") in kinds and ("single", "볼트셀") in kinds
    assert not any(c.entity == "글로벡스" for c in cands)
    # 모자이크에 들어간 신호는 단일 후보로 또 나오지 않는다
    assert not any(c.kind == "single" and c.entity == "가상자동차" for c in cands)
    m = next(c for c in cands if c.kind == "mosaic")
    candidates.score(m, w, chs, NOW)
    m.domestic = {"count": 0, "queries": ["q"], "examples": [], "days": 30}
    before = m.score
    candidates.score(m, w, chs, NOW)
    assert m.score == before + 5 and "국내 보도 0건" in m.reasons


def test_domestic_check(monkeypatch):
    w = _watch()
    c = candidates.Candidate("mosaic", "가상자동차", "테스트주 오크카운티", [_sig("gov_press", "g", ["가상자동차"])])
    assert domestic.heuristic_queries(c, w) == ["가상차 테스트주 주정부"]
    assert domestic.check(["x"], {}, 30, NOW) is None  # 네이버 키 없음 → 미확인

    def fake(q, pages, client_id=None, client_secret=None):
        return [collect.Article(title="가상차 테스트주 주정부 지원 확대", link="https://n/1", press="가상일보",
                                published=datetime(2026, 10, 10, tzinfo=timezone.utc)),
                collect.Article(title="가상차 다른 기사", link="https://n/2",
                                published=datetime(2026, 10, 10, tzinfo=timezone.utc)),
                collect.Article(title="가상차 테스트주 주정부 옛 기사", link="https://n/3",
                                published=datetime(2026, 1, 1, tzinfo=timezone.utc))]

    d = domestic.check(["가상차 테스트주 주정부"], {"naver_client_id": "id"}, 30, NOW, fetch=fake)
    assert d["count"] == 1 and d["examples"][0][0] == "가상일보"


# ---------------------------------------------------------------- 레이더 전체

@pytest.fixture
def fake_net(monkeypatch):
    calls = {"sec": 0, "courts": 0, "gnews": [], "llm": []}

    def fake_get_json(url, params=None, headers=None, timeout=20):
        if "efts.sec.gov" in url:
            calls["sec"] += 1
            return _json("sec_fts.json") if params["q"] == '"Bolt Cells"' else {"hits": {"hits": []}}
        if "courtlistener" in url:
            calls["courts"] += 1
            return _json("courts_r.json") if params["type"] == "r" else _json("courts_o.json")
        if "products/vehicle/models" in url:
            return _json("nhtsa_models.json")
        if "recallsByVehicle" in url:
            return _json("nhtsa_recalls.json")
        raise AssertionError(url)

    def fake_gnews(q, hl="en-US", gl="US", ceid="US:en"):
        calls["gnews"].append(q)
        if "site:a.gov" in q:
            return collect.parse_google_news((FIX / "gov_press.xml").read_bytes(), q)
        if "Riverton" in q:
            return collect.parse_google_news((FIX / "local.xml").read_bytes(), q)
        return []

    monkeypatch.setattr(http, "get_json", fake_get_json)
    monkeypatch.setattr(news, "fetch_google_news", fake_gnews)
    monkeypatch.setattr(reverse.collect, "fetch_google_news", fake_gnews)
    monkeypatch.setattr(sec_edgar, "document_text", lambda url, email="", max_chars=4000: "Fictional exhibit text")
    monkeypatch.setattr(radar.time, "sleep", lambda s: None)
    monkeypatch.setattr(news.time, "sleep", lambda s: None)
    monkeypatch.setattr(reverse.time, "sleep", lambda s: None)
    monkeypatch.setattr(nhtsa.time, "sleep", lambda s: None)
    return calls


def _config(tmp_path):
    cfg = load_config("없음.json")
    wfile = tmp_path / "watchlist.json"
    wfile.write_text((FIX / "watchlist.json").read_text(encoding="utf-8"), encoding="utf-8")
    cfg = _merge(cfg, {"osint": {"watchlist_file": str(wfile), "db_file": str(tmp_path / "osint.db")}})
    chs = cfg["osint"]["channels"]
    chs["gov_press"]["sites"] = ["a.gov"]
    chs["nhtsa"]["makes"] = {"ACME": "가상자동차"}
    chs["nhtsa"]["model_years"] = 1
    for k in ("pr_wire", "eu_comp", "trade_media", "china_media"):
        chs[k]["enabled"] = False
    chs["feeds"]["list"] = []
    return cfg


def test_radar_end_to_end(tmp_path, fake_net):
    cfg = _config(tmp_path)
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    st = res["status"]
    assert st["sec"]["count"] == 1 and st["courts"]["count"] == 2 and st["nhtsa"]["count"] == 1
    assert st["gov_press"]["count"] == 2 and st["local_media"]["count"] == 1
    # 추적 대상과 무관한 신호(군 박람회)는 빠진다
    titles = [s.title for s in res["signals"]]
    assert not any("county fair" in t for t in titles)
    kinds = {(c.kind, c.entity, c.location) for c in res["cands"]}
    assert ("mosaic", "가상자동차", "테스트주 오크카운티") in kinds
    md = res["md"].read_text(encoding="utf-8")
    assert "[국내 보도 미확인]" in md and "📞" in md and "채널 상태" in md
    html = res["html"].read_text(encoding="utf-8")
    assert "OSINT 데스크 리포트" in html
    # SEC 공시 원문 일부를 후보 자료로 붙인다
    sec_c = [s for c in res["cands"] for s in c.signals if s.channel == "sec"]
    assert sec_c and sec_c[0].meta["doc_text"] == "Fictional exhibit text"

    # 두 번째 실행: 같은 신호는 새 신호가 아니다(후보 없음). NHTSA는 최근 확인해 건너뛴다.
    res2 = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out2", now=NOW)
    assert not res2["cands"] and res2["status"]["nhtsa"]["count"] == 0


def test_radar_ai_prompt_and_split(tmp_path, fake_net, monkeypatch):
    seen = {}

    def fake_llm(system, user, config):
        seen.update(system=system, user=user)
        return "### 후보 C1\n🚨 **[선제 보도 후보 · 국내 미보도]** 가제\n\n### 후보 C2 · 보류\n이유"

    monkeypatch.setitem(radar.PROVIDERS, "claude", ("Claude", fake_llm))
    cfg = _config(tmp_path)
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW, use_ai=True)
    assert "근거 등급" in seen["system"] and "'단독' 표기를 쓰지 않는다" in seen["system"]
    assert "### 후보 C1" in seen["user"] and "국내 보도(자동 검색)" in seen["user"]
    parts = report.split_ai(res["ai"]["Claude"])
    assert set(parts) == {"C1", "C2"}
    assert "Claude 발제문" in res["html"].read_text(encoding="utf-8")


def test_telegram_send(monkeypatch, tmp_path, fake_net):
    from osint import notify
    sent = []
    monkeypatch.setattr(notify, "send", lambda token, chat, text: sent.append((token, chat, text)) or True)
    cfg = _config(tmp_path)
    cfg.update(telegram_bot_token="T", telegram_chat_id="C")
    res = radar.run(cfg, log=lambda m: None, out_dir=tmp_path / "out", now=NOW)
    assert len(sent) == len(res["cands"]) and sent[0][0] == "T"


# ---------------------------------------------------------------- 역추적

def test_parse_json_variants():
    assert reverse.parse_json('설명\n```json\n{"a": 1}\n```') == {"a": 1}
    assert reverse.parse_json('앞 {"a": 2} 뒤') == {"a": 2}
    assert reverse.parse_json("없음") is None


def test_reverse_with_ai(tmp_path, fake_net, monkeypatch):
    prompts_seen = []

    def fake_llm(system, user, config):
        prompts_seen.append(user)
        if system == prompts.REVERSE_EXTRACT_SYSTEM:
            return json.dumps({"entities": [{"ko": "가상자동차", "en": "Bolt Cells"}],
                               "claims": [{"id": "K1", "text": "300명 채용", "numbers": ["300"]}],
                               "queries_en": ['"Acme Motors" Riverton'], "queries_zh": []})
        return "## 1. 1차 출처 추정\n- [S1]"

    monkeypatch.setitem(reverse.PROVIDERS, "claude", ("Claude", fake_llm))
    cfg = _config(tmp_path)
    res = reverse.run("가상차가 테스트주에서 300명을 채용한다고 밝혔다.", cfg, log=lambda m: None,
                      out_dir=tmp_path / "out", now=NOW)
    titles = [s.title for s in res["sources"]]
    assert any("300 job openings" in t for t in titles)   # 외신(지방지)
    assert any(t.startswith("[8-K]") for t in titles)     # SEC 전문 검색
    assert "[S1]" in prompts_seen[-1] and "300명 채용" in prompts_seen[-1]
    assert "역추적 리포트" in res["md"].read_text(encoding="utf-8")


def test_reverse_without_ai_uses_watchlist(tmp_path, fake_net):
    cfg = _config(tmp_path)
    res = reverse.run("가상차가 오크카운티 공장을 늘린다.", cfg, log=lambda m: None, use_ai=False,
                      out_dir=tmp_path / "out", now=NOW)
    assert res["extract"]["queries_en"][0] == '"Acme Motors"'
    assert not res["ai"]
