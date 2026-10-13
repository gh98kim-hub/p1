import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from balje import analyze, collect, pitch
from balje.__main__ import main
from balje.config import load_config

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "sample_articles.json"


def _clusters(config=None):
    config = config or load_config("없는파일.json")
    articles = analyze.dedupe(collect.load_articles(SAMPLE))
    clusters = analyze.enrich(analyze.cluster_articles(articles), config, {})
    return clusters, config


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
    assert sizes == [5, 3, 2, 2, 1, 1]
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
    config = load_config("없는파일.json")
    articles = analyze.dedupe(collect.load_articles(SAMPLE))
    history = {a.link: datetime.now(timezone.utc).isoformat() for a in articles if "A자동차" in a.title}
    clusters = analyze.enrich(analyze.cluster_articles(articles), config, history)
    a_issue = next(c for c in clusters if "A자동차" in c.headline)
    assert not a_issue.is_new


def test_my_press_covered():
    clusters, _ = _clusters(dict(load_config("없는파일.json"), my_press="가상통신"))
    d = next(c for c in clusters if "D차" in c.headline)
    assert d.my_press_covered


def test_ai_pitches_request_shape(monkeypatch):
    captured = {}

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            block = types.SimpleNamespace(type="text", text="## 발제 1. 테스트")
            return types.SimpleNamespace(stop_reason="end_turn", content=[block])

    class FakeClient:
        def __init__(self):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._stream))

        def _stream(self, **kw):
            captured.update(kw)
            return FakeStream()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = FakeClient
    for name in ("AuthenticationError", "RateLimitError", "APIStatusError", "APIConnectionError"):
        setattr(fake, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    clusters, config = _clusters()
    for i, c in enumerate(clusters):
        for j, a in enumerate(c.articles):
            a.id = f"A{i}{j}"
    notes = {c.id: pitch.rule_based_notes(c, config) for c in clusters}
    mats = [{"name": "메모.txt", "text": "자료 본문"}]
    text = pitch.ai_pitches(clusters, mats, notes, config)

    assert text == "## 발제 1. 테스트"
    assert captured["model"] == "claude-opus-5-5"
    assert captured["fallbacks"] == "default"
    assert "자료에 없는 사실" in captured["system"]
    user = captured["messages"][0]["content"]
    assert "[M1] 메모.txt" in user and "자료 본문" in user


def test_cli_end_to_end(tmp_path):
    out = tmp_path / "out"
    rc = main(["--input", str(SAMPLE), "--hours", "0", "--no-history", "--out", str(out),
               "--config", str(tmp_path / "none.json")])
    assert rc == 0
    md = next(out.glob("발제노트_*.md")).read_text(encoding="utf-8")
    html = next(out.glob("발제노트_*.html")).read_text(encoding="utf-8")
    assert "오늘의 이슈 순위" in md and "[A001]" in md
    assert "<html" in html and "B모터스" in html
