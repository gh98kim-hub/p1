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
    assert sizes == [5, 3, 2, 2, 2, 1, 1, 1, 1, 1]
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
    assert "오늘의 이슈 순위" in md and "[A001]" in md
    assert "<html" in html and "B모터스" in html
    assert "보도자료 점검" in md and "묶어보기" in md and "브랜드별 기사량" in md and "틀어보기" in md
