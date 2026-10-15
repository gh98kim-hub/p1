"""추적 대상을 키워드로 고치기(빠른 추가·편집 창)."""

import json
import os

import pytest

from osint import watchlist as wl

from test_osint import FIX


def _copy(tmp_path):
    p = tmp_path / "watchlist.json"
    p.write_text((FIX / "watchlist.json").read_text(encoding="utf-8"), encoding="utf-8")
    return p


def test_split_and_parse_keywords():
    words = wl.parse_keywords("현대모비스, Hyundai Mobis\n现代摩比斯，Mobis, 현대모비스")
    assert words == ["현대모비스", "Hyundai Mobis", "现代摩比斯", "Mobis"]
    assert wl.split_keywords(words) == {"ko": ["현대모비스"], "en": ["Hyundai Mobis", "Mobis"], "zh": ["现代摩比斯"]}


def test_quick_add_new_and_merge(tmp_path):
    p = _copy(tmp_path)
    data = wl.load(p)
    e, created = wl.quick_add(data, "현대모비스, Hyundai Mobis, 现代摩比斯", "high")
    assert created and e == {"name": "현대모비스", "priority": "high", "ko": ["현대모비스"], "en": ["Hyundai Mobis"],
                             "zh": ["现代摩比斯"], "exclude": []}
    # 같은 이름이면 키워드를 보태고 중요도·제외어·다른 칸은 그대로
    e2, created2 = wl.quick_add(data, "가상자동차, Acme Motor Works", "low")
    assert not created2 and e2["priority"] == "high" and e2["exclude"] == ["Acme Bank"]
    assert e2["en"] == ["Acme Motors", "Acme", "Acme Motor Works"] and "가상차" in e2["ko"]
    wl.save(data, p)
    again = wl.load(p)
    assert wl.entity(again, "현대모비스")["en"] == ["Hyundai Mobis"]
    assert json.loads(p.read_text(encoding="utf-8"))["_설명"]            # 설명 칸 유지
    # 저장한 대상으로 실제 매칭된다
    assert "현대모비스" in wl.match_entities("Hyundai Mobis opens a plant", again)
    with pytest.raises(wl.WatchlistError):
        wl.quick_add(data, " , ")


def test_validate_and_warnings(tmp_path):
    data = wl.load(_copy(tmp_path))
    data["entities"].append(dict(data["entities"][0]))
    with pytest.raises(wl.WatchlistError, match="겹칩니다"):
        wl.save(data, tmp_path / "x.json")
    assert not (tmp_path / "x.json").exists()
    w = wl.warnings(wl.make_entity("현대모비스", ["모비스"], "high"))
    assert any("영문 키워드가 없으면" in x for x in w) and any("중문" in x for x in w)
    w = wl.warnings(wl.make_entity("가", ["Kia", "Ab"], "mid"))
    assert any("짧은 영문 키워드(Ab)" in x for x in w)               # Kia는 단어 단위로 찾으므로 괜찮다
    assert not any("짧은" in x for x in wl.warnings(wl.make_entity("가", ["Kia", "SK", "SK On"], "mid")))


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


def test_editor_edit_add_delete_save(tmp_path, tk_root, monkeypatch):
    from balje.watch_editor import WatchlistEditor
    p = _copy(tmp_path)
    saved = []
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *a, **k: True)
    ed = WatchlistEditor(tk_root, p, on_saved=lambda: saved.append(1))
    ed.update()
    assert len(ed.ent_list.get_children()) == 3
    # 고르기만 하고 바꾸지 않으면 '고침'이 아니다
    ed.ent_list.selection_set("0")
    ed.update()
    ed._select_entity()
    assert not ed._commit_entity() and not ed.dirty
    assert ed.e_kw.get("1.0", "end").strip() == "가상차, Acme Motors, Acme, 艾克米汽车"
    # 키워드 고치기
    ed.e_kw.delete("1.0", "end")
    ed.e_kw.insert("1.0", "가상차, Acme Motors, Acme Motor Works\n艾克米汽车")
    ed.e_prio.set("낮음")
    ed.update()
    assert "영문 2개: Acme Motors, Acme Motor Works" in ed.e_preview["text"]
    # 빠른 추가 → 새 대상이 선택된다
    ed.quick_text.set("볼트에너지, Bolt Energy")
    ed.quick_add()
    assert ed.e_name.get() == "볼트에너지" and ed.dirty
    # 삭제
    ed.ent_list.selection_set("1")
    ed.update()
    ed._select_entity()
    ed.delete_entity()
    # 지역 추가
    ed.new_location()
    ed.l_name.set("테스트주 강변")
    ed.l_ko.set("테스트주")
    ed.l_kw.insert("1.0", "River Side, Oak Valley")
    assert ed.save() and saved == [1] and not ed.dirty
    data = wl.load(p)
    names = [e["name"] for e in data["entities"]]
    assert names == ["가상자동차", "글로벡스", "볼트에너지"]             # 볼트셀 삭제
    acme = wl.entity(data, "가상자동차")
    assert acme["priority"] == "low" and acme["en"] == ["Acme Motors", "Acme Motor Works"]
    assert acme["zh"] == ["艾克米汽车"] and acme["exclude"] == ["Acme Bank"]
    loc = wl.location(data, "테스트주 강변")
    assert loc == {"name": "테스트주 강변", "ko": "테스트주", "en": ["River Side", "Oak Valley"], "zh": []}
    ed.destroy()


def test_editor_close_asks_to_save(tmp_path, tk_root, monkeypatch):
    from balje.watch_editor import WatchlistEditor
    p = _copy(tmp_path)
    monkeypatch.setattr("tkinter.messagebox.askyesnocancel", lambda *a, **k: None)   # 취소
    ed = WatchlistEditor(tk_root, p)
    ed.quick_text.set("새회사, New Co Holdings")
    ed.quick_add()
    ed.close()
    assert ed.winfo_exists()                                    # 취소하면 창이 그대로
    monkeypatch.setattr("tkinter.messagebox.askyesnocancel", lambda *a, **k: True)
    ed.close()
    assert wl.entity(wl.load(p), "새회사")
