import dataclasses
import json

import mss
import pytest

import autofish.locate as locate
from autofish.locate import (
    DEFAULT_ROI_PATH,
    ROI_SOURCE_DEFAULT,
    ROI_SOURCE_MANUAL,
    BarMark,
    Roi,
    bar_ref_path,
    clear_bar_mark,
    clear_bar_ref,
    default_center_roi,
    load_bar_mark,
    load_roi,
    load_roi_source,
    primary_screen_size,
    save_roi,
)
from common.paths import data_root

ROI = Roi(left=10, top=20, width=300, height=40)
BAR = BarMark(left=5.0, right=105.0, top=3.0, height=12.0, frame_width=600.0)


def read_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_roi_as_mss_allows_negative_origin():
    roi = Roi(left=-1920, top=-5, width=100, height=50)
    assert roi.as_mss() == {"left": -1920, "top": -5, "width": 100, "height": 50}


@pytest.mark.parametrize("w,h", [(0, 10), (10, 0), (-1, 10)])
def test_roi_rejects_non_positive_size_and_is_frozen(w, h):
    with pytest.raises(ValueError):
        Roi(left=0, top=0, width=w, height=h)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ROI.left = 1  # type: ignore[misc]


def test_default_center_roi():
    assert default_center_roi(1920, 1080) == Roi(left=720, top=405, width=480, height=270)
    assert default_center_roi(40, 20) == Roi(left=4, top=0, width=32, height=20)
    for w, h in [(0, 100), (100, 0), (-5, 5)]:
        with pytest.raises(ValueError):
            default_center_roi(w, h)


def fake_mss_with(monitors):
    class FakeMss:
        def __init__(self):
            self.monitors = monitors

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return FakeMss


def test_primary_screen_size_uses_mss_monitors(monkeypatch):
    all_mon = {"left": 0, "top": 0, "width": 3000, "height": 2000}
    primary = {"left": 0, "top": 0, "width": 1512, "height": 982}
    monkeypatch.setattr(mss, "mss", fake_mss_with([all_mon, primary]))
    assert primary_screen_size() == (1512, 982)
    monkeypatch.setattr(mss, "mss", fake_mss_with([all_mon]))
    assert primary_screen_size() == (3000, 2000)


def test_bar_mark_validation_width_and_box():
    with pytest.raises(ValueError):
        BarMark(left=10.0, right=17.9)
    with pytest.raises(ValueError):
        BarMark(left=0.0, right=50.0, height=-1.0)
    bar = BarMark(left=10.0, right=60.0, top=4.0)
    assert bar.width == 50.0
    assert bar.as_box() == (10.0, 4.0, 50.0, 1.0)
    assert BAR.as_box() == (5.0, 3.0, 100.0, 12.0)


def test_bar_mark_box_for_frame_scaling():
    assert BAR.box_for_frame(1200.0, 300.0) == (10.0, 6.0, 200.0, 24.0)
    legacy = BarMark(left=5.0, right=105.0, top=3.0, height=12.0)
    assert legacy.box_for_frame(600.0, 300.0) == (10.0, 6.0, 200.0, 24.0)
    assert legacy.box_for_frame(600.0, 0.0) == legacy.as_box()


def test_save_and_load_roi_roundtrip(tmp_path):
    p = tmp_path / "nested" / "dir" / "roi.json"
    assert save_roi(ROI, p) == p
    assert p.is_file()
    assert load_roi(p) == ROI
    with pytest.raises(FileNotFoundError):
        load_roi(tmp_path / "missing.json")


def test_source_rules(tmp_path):
    p = tmp_path / "roi.json"
    assert load_roi_source(p) == ROI_SOURCE_DEFAULT  # 无文件

    save_roi(ROI, p)
    assert load_roi_source(p) == ROI_SOURCE_MANUAL  # 新文件默认 manual
    save_roi(ROI, p, source=ROI_SOURCE_DEFAULT)
    assert load_roi_source(p) == ROI_SOURCE_DEFAULT
    save_roi(ROI, p)
    assert load_roi_source(p) == ROI_SOURCE_DEFAULT  # source=None 沿用
    save_roi(ROI, p, source="whatever")
    assert load_roi_source(p) == ROI_SOURCE_MANUAL

    p.write_text("{not json", encoding="utf-8")
    assert load_roi_source(p) == ROI_SOURCE_MANUAL
    p.write_text(json.dumps(ROI.as_mss()), encoding="utf-8")
    assert load_roi_source(p) == ROI_SOURCE_MANUAL
    p.write_text(json.dumps({**ROI.as_mss(), "source": "  DEFAULT "}), encoding="utf-8")
    assert load_roi_source(p) == ROI_SOURCE_DEFAULT
    p.write_text(json.dumps({**ROI.as_mss(), "source": "auto"}), encoding="utf-8")
    assert load_roi_source(p) == ROI_SOURCE_MANUAL


def test_save_roi_bar_handling(tmp_path):
    p = tmp_path / "roi.json"
    save_roi(ROI, p, bar=BAR)
    assert load_bar_mark(p) == BAR

    other = Roi(left=0, top=0, width=500, height=60)
    save_roi(other, p, keep_bar=True)
    assert load_roi(p) == other
    assert load_bar_mark(p) == BAR

    new_bar = BarMark(left=1.0, right=41.0)
    save_roi(other, p, bar=new_bar, keep_bar=True)
    assert load_bar_mark(p) == new_bar
    assert "bar_frame_width" not in read_json(p)

    save_roi(ROI, p)  # 重框：默认清条界
    assert load_bar_mark(p) is None
    assert load_roi(p) == ROI


def test_load_bar_mark_none_cases(tmp_path):
    p = tmp_path / "roi.json"
    assert load_bar_mark(p) is None
    save_roi(ROI, p)
    assert load_bar_mark(p) is None
    p.write_text(
        json.dumps({**ROI.as_mss(), "bar_left": 10.0, "bar_right": 12.0}), encoding="utf-8"
    )
    assert load_bar_mark(p) is None


def test_clear_bar_mark_keeps_roi_and_source(tmp_path):
    p = tmp_path / "roi.json"
    clear_bar_mark(p)  # 缺文件静默
    assert not p.exists()
    save_roi(ROI, p, bar=BAR, source=ROI_SOURCE_DEFAULT)
    clear_bar_mark(p)
    assert load_bar_mark(p) is None
    assert load_roi(p) == ROI
    assert load_roi_source(p) == ROI_SOURCE_DEFAULT
    assert not any(k.startswith("bar_") for k in read_json(p))


def test_bar_ref_path_and_clear(tmp_path):
    p = tmp_path / "sub" / "roi.json"
    ref = bar_ref_path(p)
    assert ref == tmp_path / "sub" / "bar_ref.png"
    assert bar_ref_path() == data_root() / "bar_ref.png"
    assert bar_ref_path(DEFAULT_ROI_PATH) == data_root() / "bar_ref.png"

    clear_bar_ref(p)  # 缺失静默
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"png")
    from autofish.locate.roi import bar_ref_meta_path

    meta = bar_ref_meta_path(p)
    meta.write_text('{"program_bar":[1,2,3,4]}\n', encoding="utf-8")
    clear_bar_ref(p)
    assert not ref.exists()
    assert not meta.exists()


def test_default_path_used_when_path_is_none(tmp_path, monkeypatch):
    assert DEFAULT_ROI_PATH == data_root() / "roi.json"
    fake_default = tmp_path / "data" / "roi.json"
    # 默认路径在导入时定值，只能替换模块常量，避免写仓库 data/
    monkeypatch.setattr(locate.roi, "DEFAULT_ROI_PATH", fake_default)
    monkeypatch.setattr(locate.roi, "DEFAULT_BAR_REF_PATH", tmp_path / "data" / "bar_ref.png")

    assert load_roi_source() == ROI_SOURCE_DEFAULT
    assert load_bar_mark() is None
    assert save_roi(ROI, bar=BAR, source=ROI_SOURCE_DEFAULT) == fake_default
    assert load_roi() == ROI
    assert load_bar_mark() == BAR
    assert load_roi_source() == ROI_SOURCE_DEFAULT
    clear_bar_mark()
    assert load_bar_mark() is None

    ref = bar_ref_path()
    assert ref == tmp_path / "data" / "bar_ref.png"
    ref.write_bytes(b"png")
    clear_bar_ref()
    assert not ref.exists()
