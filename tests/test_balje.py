import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from balje import analyze, collect, llm, pitch
from balje.__main__ import main
from balje.config import _merge, load_config, search_queries

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "sample_articles.json"
SAMPLE_CFG = ROOT / "samples" / "sample_config.json"


def _config(**over):
    cfg = _merge(load_config("없는파일.json"), json.loads(SAMPLE_CFG.read_text(encoding="utf-8")))
    return _merge(cfg, over)


def _clusters(config=None):
    config = config or _config()
    articles = analyze.dedupe(collect.load_articles(SAMPLE))
    clusters = analyze.enrich(analyze.cluster_articles(articles), config, {})
    return clusters, config


def _by(clusters, word):
    return next(c for c in clusters if word in c.headline)


def test_clean_text_and_press():
    assert collect.clean_text("<b>현대차</b> &quot;신차&quot;") == '현대차 "신차"'
    assert collect.press_from_url("https://www.yna.co.kr/view/AKR1") == "연합뉴스"
    assert collect.press_from_url("https://biz.chosun.com/x") == "조선비즈"
    assert collect.press_from_url("https://news.chosun.com/x") == "조선일보"


def test_parse_date_formats():
    a = collect.parse_date("Mon, 13 Oct 2026 07:31:00 +0900")
    b = collect.parse_date("2026-10-13 07:31")
    assert a == b


def test_load_csv_with_korean_headers(tmp_path):
    f = tmp_path / "monitor.csv"
    f.write_text("제목,링크,언론사,일시\nA자동차 신차 공개,https://example.com/1,가상일보,2026-10-13 09:00\n",
                 encoding="utf-8-sig")
    [a] = collect.load_articles(f)
    assert (a.title, a.press, a.published.hour) == ("A자동차 신차 공개", "가상일보", 9)


def test_load_json_wrapped_in_items(tmp_path):
    f = tmp_path / "monitor.json"
    f.write_text(json.dumps({"items": [{"title": "<b>기아</b> 판매", "originallink": "https://www.mk.co.kr/1"}]}),
                 encoding="utf-8")
    [a] = collect.load_articles(f)
    assert (a.title, a.press) == ("기아 판매", "매일경제")


def test_clustering_groups_same_issue():
    clusters, _ = _clusters()
    sizes = sorted((len(c.articles) for c in clusters), reverse=True)
    assert sizes == [5, 3, 2, 2, 2, 2, 1, 1, 1, 1, 1]
    top = clusters[0]
    assert "A자동차" in top.headline and not top.headline.startswith("[")
    assert {"실적", "관세·통상"} <= set(top.angles)
    assert "3조2천억원" in top.numbers


def test_exclusive_flag_and_notes():
    clusters, config = _clusters()
    ev = next(c for c in clusters if "B모터스" in c.headline)
    assert ev.exclusive
    notes = pitch.rule_based_notes(ev, config)
    assert "타사 단독" in notes["status"]
    assert notes["angles"][0].startswith("[후속]")


def test_history_marks_continuing_issue():
    config = _config()
    articles = analyze.dedupe(collect.load_articles(SAMPLE))
    history = {a.link: datetime.now(timezone.utc).isoformat() for a in articles if "A자동차" in a.title}
    clusters = analyze.enrich(analyze.cluster_articles(articles), config, history)
    a_issue = next(c for c in clusters if "A자동차" in c.headline)
    assert not a_issue.is_new


def test_my_press_covered():
    clusters, _ = _clusters(_config(my_press="가상통신"))
    d = next(c for c in clusters if "D차" in c.headline)
    assert d.my_press_covered


def _fake_anthropic(monkeypatch, captured):
    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            block = types.SimpleNamespace(type="text", text="## 발제 1. 테스트")
            return types.SimpleNamespace(stop_reason="end_turn", content=[block])

    class FakeClient:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._stream))

        def _stream(self, **kw):
            captured.update(kw)
            return FakeStream()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = FakeClient
    for name in ("AuthenticationError", "RateLimitError", "APIStatusError", "APIConnectionError"):
        setattr(fake, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def _fake_gemini(monkeypatch, captured, text="## 제미나이 발제"):
    class Models:
        def generate_content(self, model, contents, config):
            captured.update(model=model, contents=contents, config=config)
            return types.SimpleNamespace(text=text, candidates=[types.SimpleNamespace(finish_reason="STOP")],
                                         prompt_feedback=None)

    class Client:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.models = Models()

    genai = types.ModuleType("google.genai")
    genai.Client = Client
    genai_types = types.ModuleType("google.genai.types")
    genai_types.GenerateContentConfig = lambda **kw: kw
    errors = types.ModuleType("google.genai.errors")
    errors.APIError = type("APIError", (Exception,), {})
    errors.ClientError = type("ClientError", (errors.APIError,), {})
    genai.types, genai.errors = genai_types, errors
    google = types.ModuleType("google")
    google.genai = genai
    for name, mod in {"google": google, "google.genai": genai, "google.genai.types": genai_types,
                      "google.genai.errors": errors}.items():
        monkeypatch.setitem(sys.modules, name, mod)


def _prepared():
    clusters, config = _clusters()
    for i, c in enumerate(clusters):
        c.id = f"I{i:02d}"
        for j, a in enumerate(c.articles):
            a.id = f"A{i}{j}"
    trends = analyze.cross_trends(clusters)
    notes = {c.id: pitch.rule_based_notes(c, config, trends) for c in clusters}
    return clusters, config, trends, notes


def test_ai_claude_request_shape(monkeypatch):
    captured = {}
    _fake_anthropic(monkeypatch, captured)
    clusters, config, trends, notes = _prepared()
    config["anthropic_api_key"] = "sk-test"
    mats = [{"name": "메모.txt", "text": "자료 본문"}]
    out = pitch.ai_pitches(clusters, mats, notes, config, trends)

    assert out == {"Claude": "## 발제 1. 테스트"}
    assert captured["model"] == "claude-opus-5-5" and captured["fallbacks"] == "default"
    assert captured["api_key"] == "sk-test"
    assert "자료에 없는 사실" in captured["system"]
    user = captured["messages"][0]["content"]
    assert "[M1] 메모.txt" in user and "자료 본문" in user
    assert "# 2. 보도자료 점검" in user and "# 3. 틀어보기" in user
    assert "묶어보기 후보" in user and "보도자료 신호" in user


def test_ai_gemini_and_both(monkeypatch):
    cap_c, cap_g = {}, {}
    _fake_anthropic(monkeypatch, cap_c)
    _fake_gemini(monkeypatch, cap_g)
    clusters, config, trends, notes = _prepared()
    config["gemini_api_key"] = "g-key"

    config["ai"]["provider"] = "gemini"
    assert pitch.ai_pitches(clusters, [], notes, config, trends) == {"Gemini": "## 제미나이 발제"}
    assert cap_g["model"] == "gemini-pro-latest" and cap_g["api_key"] == "g-key"
    assert "자료에 없는 사실" in cap_g["config"]["system_instruction"]

    config["ai"]["provider"] = "both"
    out = pitch.ai_pitches(clusters, [], notes, config, trends)
    assert list(out) == ["Claude", "Gemini"]


def test_gemini_without_key(monkeypatch):
    _fake_gemini(monkeypatch, {})
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    msg = llm.call_gemini("s", "u", {"ai": {}})
    assert "API 키가 없습니다" in msg


def test_release_detection_and_review():
    clusters, config, trends, notes = _prepared()
    promo = _by(clusters, "할인 프로모션")
    assert promo.release_kind == "홍보성"
    assert notes[promo.id]["release"]["verdict"] == "묶음 기획 소재"
    wire = _by(clusters, "무상점검")
    assert any("뉴스와이어" in s for s in wire.release_signals)
    # 타사 단독은 보도자료로 보지 않는다
    assert _by(clusters, "B모터스, 중형").release_kind == ""
    # 실적 기사는 보도자료 판단 대상이 아니다
    assert _by(clusters, "A자동차").release_kind == ""


def test_cross_trends_group_brands():
    clusters, _, trends, _ = _prepared()
    promo = next(t for t in trends if t["category"] == "보도자료·홍보성")
    assert set(promo["brands"]) == {"가상모터스", "나래자동차", "B모터스"}
    assert any(t["category"] == "신차" for t in trends)


def test_twists_mark_covered_views():
    clusters, config, _, notes = _prepared()
    a = _by(clusters, "A자동차")
    views = {t["view"]: t["covered"] for t in notes[a.id]["twists"]}
    assert views["협력사·부품업계로 번지는 영향"] is False
    assert 1 <= len(views) <= 5
    # 기사에 이미 나온 단어가 있으면 '이미 다룸'
    a.articles[0].description += " 협력사 부담도 커졌다."
    views = {t["view"]: t["covered"] for t in pitch.twists_for(a, config)}
    assert views.get("협력사·부품업계로 번지는 영향") is True


def test_brand_filter_and_queries():
    cfg = load_config("없는파일.json")
    qs = search_queries(cfg)
    assert "현대차" in qs and "MINI 코리아" in qs and len(qs) == len(set(qs))
    arts = [collect.Article(title="기아 타이거즈 연승", link="1", keyword="기아"),
            collect.Article(title="기아 신차 출시", link="2", keyword="기아"),
            collect.Article(title="관세 협상 타결", link="3", keyword="자동차 관세")]
    kept = analyze.filter_auto(arts, [b["query"] for b in cfg["brands"]], cfg["auto_terms"])
    assert [a.link for a in kept] == ["2", "3"]
    # 대문자 약어는 대소문자 구분
    assert analyze.brand_hits("미니멀 디자인 mini", cfg["brands"]) == []
    assert "MINI" in analyze.brand_hits("MINI 쿠퍼 출시", cfg["brands"])


def test_cli_end_to_end(tmp_path):
    out = tmp_path / "out"
    rc = main(["--input", str(SAMPLE), "--hours", "0", "--no-history", "--out", str(out),
               "--config", str(SAMPLE_CFG)])
    assert rc == 0
    md = next(out.glob("발제노트_*.md")).read_text(encoding="utf-8")
    html = next(out.glob("발제노트_*.html")).read_text(encoding="utf-8")
    for title in ("1. 발제 후보", "2. AI 발제안", "3. 보도자료 점검", "4. 묶음 기획 소재",
                  "5. 앵글 바꾸기", "6. 외신", "7. 브랜드별 기사량", "8. 전체 이슈 목록"):
        assert f"## {title}" in md
    assert "<html" in html and "B모터스" in html


# ---------------------------------------------------------------- 본문·외신·정렬·링크

FIX = ROOT / "tests" / "fixtures"


def test_extract_body_naver_and_generic():
    raw = (FIX / "naver_article.html").read_bytes()
    body = collect.extract_body(collect._decode(raw, None))
    assert body.startswith("부제목 첫 줄\n부제목 둘째 줄\n")
    assert "\n가상자동차가 13일" in body and "업계는 연말 출시를 예상한다." in body
    assert "사진 설명" not in body and "스크립트" not in body and "기자" not in body
    raw = (FIX / "generic_article.html").read_bytes()  # euc-kr
    body = collect.extract_body(collect._decode(raw, None))
    assert "3분기 국내 판매가 2만대" in body and "메뉴" not in body and "짧은줄" not in body
    assert collect.extract_body("<html><body><p>짧다</p></body></html>") == ""


def test_parse_google_news():
    arts = collect.parse_google_news((FIX / "google_news.xml").read_bytes(), "q")
    assert [a.press for a in arts] == ["Example Wire", "Sample Times"]
    assert arts[0].title == "Acme Motors to build new EV plant in Georgia"
    assert arts[0].description == "" and arts[0].lang == "en" and arts[0].published.hour == 1


def test_normalize_link():
    assert collect.normalize_link("www.example.com/a") == "https://www.example.com/a"
    assert collect.normalize_link("//example.com/a") == "https://example.com/a"
    assert collect.normalize_link("http://example.com") == "http://example.com"
    assert collect.normalize_link("") == ""


def test_sort_latest_and_articles_newest_first():
    clusters, _ = _clusters()
    latest = analyze.sort_clusters(clusters, "latest")
    times = [c.latest for c in latest]
    assert times == sorted(times, reverse=True)
    assert analyze.sort_clusters(clusters, "score")[0].score == max(c.score for c in clusters)
    for c in clusters:
        ts = [a.published for a in c.articles]
        assert ts == sorted(ts, reverse=True)
    # 대표 제목은 정렬과 무관하게 유지
    assert _by(clusters, "A자동차").headline == "A자동차 3분기 영업이익 감소…관세 부담 반영"


def test_foreign_cluster_flag():
    clusters, _ = _clusters()
    f = [c for c in clusters if c.foreign]
    assert len(f) == 1 and len(f[0].articles) == 2 and f[0].release_kind == ""
    assert "Acme Motors" in f[0].brands


def _run_full(tmp_path, monkeypatch, **cfg_over):
    """네트워크 수집을 가짜로 바꿔 파이프라인 전체를 돌린다."""
    from balje import pipeline
    sample = collect.load_articles(SAMPLE)
    ko = [a for a in sample if a.lang == "ko"]
    for a in ko[:3]:
        a.naver_link = "https://n.news.naver.com/mnews/article/001/" + a.link[-1]
    monkeypatch.setattr(collect, "fetch_naver", lambda kw, *a, **k: [x for x in ko if x.keyword == "" and kw == "완성차"])
    monkeypatch.setattr(collect, "fetch_google_news", lambda q, *a, **k: collect.parse_google_news(
        (FIX / "google_news.xml").read_bytes(), q) if q == "Hyundai Motor" else [])
    fetched = []

    def fake_body(a, max_chars=6000):
        fetched.append(a)
        return f"{a.title} 본문 전문입니다. " * 5

    monkeypatch.setattr(collect, "fetch_body", fake_body)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    cfg = _config(search_brands=False, keywords=["완성차"], **cfg_over)
    cfg["foreign"] = dict(cfg["foreign"], enabled=True, queries=["Hyundai Motor", "Tesla"])
    cfg["bodies"] = dict(cfg["bodies"], enabled=True, issues=3, per_issue=2)
    cfg["history_file"] = str(tmp_path / "h.json")
    res = pipeline.run(cfg, hours=0, out_dir=tmp_path / "out", log=lambda m: None)
    return res, fetched


def test_pipeline_bodies_only_for_candidates(tmp_path, monkeypatch):
    res, fetched = _run_full(tmp_path, monkeypatch)
    assert fetched and len(fetched) <= 6
    by_id = {a.link: c for c in res["clusters"] for a in c.articles}
    for a in fetched:
        c = by_id[a.link]
        assert not c.release_kind and not c.foreign
    body_md = res["body_md"].read_text(encoding="utf-8")
    assert "본문 전문입니다" in body_md
    md = res["md"].read_text(encoding="utf-8")
    assert "## 6. 외신 (1건)" in md and "Example Wire" in md
    assert "발제 후보 기사 본문: 기사본문_" in md


def test_html_internal_links_all_resolve(tmp_path, monkeypatch):
    import re
    res, _ = _run_full(tmp_path, monkeypatch)
    h = res["html"].read_text(encoding="utf-8")
    hrefs = set(re.findall(r"href='#([^']+)'", h))
    ids = set(re.findall(r"id='([^']+)'", h))
    assert hrefs and not (hrefs - ids)
    # 외부 링크는 모두 http(s)
    ext = re.findall(r"href='([^#'][^']*)'", h)
    assert ext and all(u.startswith(("http://", "https://")) for u in ext)


def test_markdown_links_escape_brackets():
    from balje.report import _md_link
    assert _md_link("[단독] 제목", "https://e.com/a(b)") == "[\\[단독\\] 제목](<https://e.com/a(b)>)"


# ---------------------------------------------------------------- Claude 구독(Claude Code) 연결

def _fake_claude_code(monkeypatch, stdout, returncode=0):
    seen = {}

    def fake_run(cmd, input=None, capture_output=None, cwd=None, env=None, timeout=None, **kw):
        sp = cmd[cmd.index("--system-prompt-file") + 1]
        seen.update(cmd=cmd, input=input.decode("utf-8"), cwd=cwd, env=env,
                    system=Path(sp).read_text(encoding="utf-8"))
        return types.SimpleNamespace(stdout=stdout.encode("utf-8"), stderr=b"", returncode=returncode)

    monkeypatch.setattr(llm, "find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    return seen


def test_claude_subscription_runs_claude_code(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-pass")
    seen = _fake_claude_code(monkeypatch, json.dumps({"type": "result", "is_error": False, "result": "발제 결과"}))
    cfg = {"claude_auth": "subscription", "ai": {"effort": "high", "claude_code_model": "opus"}}
    assert llm.call_claude("시스템 지시", "사용자 자료 원문", cfg) == "발제 결과"
    cmd = seen["cmd"]
    assert cmd[:2] == ["/usr/bin/claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""                # 도구 없이 글만 쓴다
    assert "--no-session-persistence" in cmd and "--bare" not in cmd   # bare는 구독 로그인을 안 쓴다
    assert cmd[cmd.index("--effort") + 1] == "high" and cmd[cmd.index("--model") + 1] == "opus"
    assert seen["input"] == "사용자 자료 원문" and seen["system"] == "시스템 지시"
    assert "ANTHROPIC_API_KEY" not in seen["env"]             # 키가 있으면 구독 대신 키로 청구된다


def test_claude_subscription_errors(monkeypatch):
    _fake_claude_code(monkeypatch, json.dumps({"is_error": True, "result": "Not logged in · Please run /login"}), 1)
    msg = llm.call_claude("s", "u", {"claude_auth": "subscription", "ai": {}})
    assert "로그인이 필요합니다" in msg
    monkeypatch.setattr(llm, "find_claude", lambda: None)
    assert "설치돼 있지 않습니다" in llm.call_claude("s", "u", {"claude_auth": "subscription", "ai": {}})


def test_available_provider_subscription(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(llm, "find_claude", lambda: "/usr/bin/claude")
    assert llm.available_provider({"claude_auth": "subscription", "ai": {}}) == "claude"
    assert llm.available_provider({"claude_auth": "api", "ai": {}}) is None
    monkeypatch.setattr(llm, "find_claude", lambda: None)
    assert llm.available_provider({"claude_auth": "subscription", "ai": {}}) is None


def test_claude_code_status_parsing(monkeypatch):
    monkeypatch.setattr(llm, "find_claude", lambda: "/usr/bin/claude")

    def status(payload, code=0):
        monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
            stdout=json.dumps(payload).encode(), stderr=b"", returncode=code))
        return llm.claude_code_status()

    assert status({"loggedIn": True, "authMethod": "claude.ai"}) == (True, True, "로그인됨: 구독 계정(claude.ai)")
    assert status({"loggedIn": False, "authMethod": "none"}, 1)[1] is False
    assert "구독 요금제가 아님" in status({"loggedIn": True, "authMethod": "api_key"})[2]
