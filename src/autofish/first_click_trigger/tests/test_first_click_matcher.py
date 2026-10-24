import json
from pathlib import Path

import numpy as np
import pytest

from autofish.first_click_trigger.session_eval import (
    SessionPaths,
    backtest_recording,
    extract_range,
    format_backtest_report,
    load_session,
    load_session_raw,
    merge_nearby_hits,
    normalize_ranges,
    save_marks,
    save_session,
)
from autofish.first_click_trigger.template_matcher import TemplateMatcher

REPO = Path(__file__).resolve().parents[4]


def _matcher(kit, **kw) -> TemplateMatcher:
    m = TemplateMatcher(samplerate=kit.SR, **kw)
    m.set_template(kit.splash(), trim_energy=False)
    return m


# ---- TemplateMatcher ----


def test_matcher_without_template(kit):
    m = TemplateMatcher(samplerate=kit.SR)
    assert not m.has_template and m.template_wave is None
    assert m.feed(kit.clip()) == (False, 0.0)
    with pytest.raises(RuntimeError):
        m.clone_for_offline()
    with pytest.raises(ValueError):
        m.set_template(np.zeros(0, dtype=np.float32))


def test_set_template_truncates_and_returns_copy(kit):
    m = TemplateMatcher(samplerate=kit.SR, template_duration_s=0.5)
    m.set_template(kit.noise(3.0, level=0.3), trim_energy=False)
    assert m.has_template
    assert m.template_wave.size == 2 * kit.SR
    assert m.template_duration_s == pytest.approx(2.0)
    w = m.template_wave
    w[:] = 0
    assert np.any(m.template_wave != 0)


def test_set_template_trim_energy_cuts_silence(kit):
    pad = np.zeros(kit.SR // 2, dtype=np.float32)
    wave = np.concatenate([pad, kit.splash(), pad])
    m = TemplateMatcher(samplerate=kit.SR)
    m.set_template(wave, trim_energy=False)
    assert m.template_wave.size == wave.size
    m.set_template(wave, trim_energy=True)
    assert 0.15 * kit.SR <= m.template_wave.size < wave.size - kit.SR // 2
    assert m.template_duration_s == pytest.approx(m.template_wave.size / kit.SR)


def test_load_template_mono_float32_without_trim(kit, tmp_path):
    tpl = kit.splash()
    pad = np.zeros(kit.SR // 2)
    stereo = np.stack([np.concatenate([pad, tpl])] * 2, axis=1).astype(np.float64)
    p = tmp_path / "t.npy"
    np.save(p, stereo)
    m = TemplateMatcher(samplerate=kit.SR)
    m.load_template(p)
    w = m.template_wave
    assert w.dtype == np.float32 and w.ndim == 1 and w.size == stereo.shape[0]
    np.testing.assert_allclose(w[pad.size:], tpl, atol=1e-6)


def test_quiet_buffer_never_triggers(kit):
    m = _matcher(kit)
    assert m.feed(np.zeros(kit.SR, dtype=np.float32)) == (False, 0.0)
    assert m.last_reject == "太静"
    quiet = kit.splash() * 1e-5
    assert m.feed(quiet) == (False, 0.0)


def test_splash_triggers_then_baseline_blocks_repeat(kit):
    m = _matcher(kit)
    trig, score = m.feed(kit.clip())
    assert trig and score >= m.threshold
    trig2, score2 = m.feed(kit.noise(0.05))
    assert not trig2 and score2 >= m.threshold
    assert "未抬升" in m.last_reject
    m.reset_score_baseline()
    trig3, _ = m.feed(kit.noise(0.05))
    assert trig3


def test_update_baseline_false_does_not_raise_baseline(kit):
    m = _matcher(kit)
    assert m.feed(kit.clip(), update_baseline=False)[0]
    assert m.feed(kit.noise(0.05), update_baseline=False)[0]


def test_reset_buffer_forgets_audio(kit):
    m = _matcher(kit)
    assert m.feed(kit.clip())[0]
    m.reset_buffer()
    trig, score = m.feed(kit.noise(0.3))
    assert not trig and score < m.threshold


def test_threshold_and_dissimilar_sound(kit):
    m = _matcher(kit)
    t = np.arange(int(0.6 * kit.SR)) / kit.SR
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    trig, score = m.feed(np.concatenate([kit.noise(0.3), tone]))
    assert not trig and score < m.threshold
    strict = _matcher(kit, threshold=1.01)
    assert not strict.feed(kit.clip())[0]


def test_analyze_clip_ignores_and_keeps_baseline(kit):
    m = _matcher(kit)
    assert m.feed(kit.clip())[0]
    rep = m.analyze_clip(kit.splash())
    assert rep["would_trigger"] and rep["score"] >= m.threshold
    assert {"score", "rise", "ambient", "threshold", "reason", "would_trigger"} <= set(rep)
    assert not m.feed(kit.noise(0.05))[0]


def test_clone_for_offline_is_independent(kit):
    m = _matcher(kit, threshold=0.65)
    assert m.feed(kit.clip())[0]
    c = m.clone_for_offline()
    assert c.threshold == 0.65 and c.samplerate == kit.SR
    np.testing.assert_array_equal(c.template_wave, m.template_wave)
    assert c.feed(kit.clip())[0]
    assert not m.feed(kit.noise(0.05))[0]


def test_bump_score_baseline_blocks_lower_scores(kit):
    m = _matcher(kit)
    m.bump_score_baseline(1.0)
    trig, score = m.feed(kit.clip())
    assert not trig and score >= m.threshold


_REAL_SESSION = REPO / "data" / "audio_sessions" / "session_20260922_013531"
_REAL_TPL = REPO / "assets" / "audio" / "windows.npy"


@pytest.mark.skipif(
    not (_REAL_SESSION / "audio.npy").is_file() or not _REAL_TPL.is_file(),
    reason="仓库缺少真实会话或内置模板",
)
def test_real_session_marked_splash_matches_bundled_template():
    meta = json.loads((_REAL_SESSION / "meta.json").read_text(encoding="utf-8"))
    marks = json.loads((_REAL_SESSION / "marks.json").read_text(encoding="utf-8"))
    sr = int(meta["samplerate"])
    rng = marks["splash_ranges"][0]
    wave = np.load(_REAL_SESSION / "audio.npy", mmap_mode="r")
    seg = np.asarray(wave[int(rng["start_s"] * sr): int(rng["end_s"] * sr)], dtype=np.float32)
    m = TemplateMatcher(samplerate=sr)
    m.load_template(_REAL_TPL)
    rep = m.analyze_clip(seg)
    assert rep["would_trigger"] and rep["score"] >= m.threshold


# ---- session_eval ----


def _paths(root: Path) -> SessionPaths:
    return SessionPaths(root=root, audio=root / "audio.npy", meta=root / "meta.json",
                        marks=root / "marks.json")


def test_normalize_ranges():
    got = normalize_ranges([(3.0, 2.0), {"start_s": 0.5, "end_s": 1.0}, (4.0, 4.0001)])
    assert got == [(0.5, 1.0), (2.0, 3.0)]


def test_save_and_load_session_roundtrip(tmp_path):
    raw = np.stack([np.ones(800), np.zeros(800)], axis=1).astype(np.float32)
    p = save_session(raw, 8000, [(0.08, 0.02), (0.05, 0.05)], paths=_paths(tmp_path / "s"))
    assert p.audio.is_file() and p.meta.is_file() and p.marks.is_file()
    meta = json.loads(p.meta.read_text(encoding="utf-8"))
    assert meta == {"samplerate": 8000, "samples": 800, "channels": 2, "duration_s": 0.1}
    wave, sr, ranges = load_session(p.root)
    assert sr == 8000 and wave.shape == (800,)
    np.testing.assert_allclose(wave, 0.5)
    assert ranges == [(0.02, 0.08)]
    raw2, sr2 = load_session_raw(p.root)
    assert sr2 == 8000 and raw2.shape == (800, 2)
    save_marks(p, [{"start_s": 0.01, "end_s": 0.03}])
    assert load_session(p.root)[2] == [(0.01, 0.03)]
    np.testing.assert_array_equal(np.load(p.audio), raw)


def test_save_session_default_dir(lib_dirs):
    from autofish.first_click_trigger.paths import list_session_dirs, user_audio_sessions_dir

    p = save_session(np.zeros(80, dtype=np.float32), 8000, [])
    assert p.root.parent == user_audio_sessions_dir()
    assert p.root.name.startswith("session_")
    assert p.root in list_session_dirs()
    assert load_session(p.root)[2] == []


def test_extract_range():
    wave = np.arange(100, dtype=np.float32)
    np.testing.assert_array_equal(extract_range(wave, 10, 2.0, 3.0), np.arange(20, 30))
    np.testing.assert_array_equal(extract_range(wave, 10, 3.0, 2.0), np.arange(20, 30))
    np.testing.assert_array_equal(extract_range(wave, 10, 9.5, 20.0), np.arange(95, 100))
    seg = extract_range(wave, 10, 0.0, 1.0)
    seg[:] = -1
    assert wave[0] == 0
    with pytest.raises(ValueError):
        extract_range(wave, 10, 12.0, 13.0)
    with pytest.raises(ValueError):
        extract_range(wave, 10, 1.0, 1.0)


def test_merge_nearby_hits_keeps_highest():
    hits = [
        {"t_s": 1.0, "score": 0.8},
        {"t_s": 1.3, "score": 0.9},
        {"t_s": 2.0, "score": 0.7},
    ]
    assert [h["t_s"] for h in merge_nearby_hits(hits)] == [1.3, 2.0]
    assert merge_nearby_hits([]) == []


def test_backtest_recording_classifies_hits(kit):
    sr = kit.SR
    tpl_s = kit.splash().size / sr
    wave = np.concatenate([
        kit.noise(0.5), kit.splash(), kit.noise(3.5, seed=7), kit.splash(), kit.noise(0.5, seed=8),
    ])
    first_end = 0.5 + tpl_s
    second_end = 0.5 + tpl_s + 3.5 + tpl_s
    marks = [(0.4, first_end + 0.4), (first_end + 1.0, first_end + 1.5)]
    live = _matcher(kit)
    assert live.feed(kit.clip())[0]
    stereo = np.stack([wave, wave], axis=1)
    rep = backtest_recording(stereo, sr, live, marks)
    s = rep["summary"]
    assert (s["n_marks"], s["n_hits"], s["tp"], s["fp"], s["fn"]) == (2, 2, 1, 1, 1)
    assert s["n_raw_hits"] >= 2
    assert rep["duration_s"] == pytest.approx(wave.size / sr)
    t0, t1 = (h["t_s"] for h in rep["hits"])
    assert first_end - 0.05 <= t0 <= first_end + 0.4
    assert second_end - 0.05 <= t1 <= second_end + 0.4
    for h in rep["hits"]:
        assert h["end_s"] == h["t_s"]
        assert h["end_s"] - h["start_s"] == pytest.approx(tpl_s)
        assert h["score"] >= live.threshold and "trigger_score" in h
    assert rep["false_negative_ranges"] == [{"start_s": marks[1][0], "end_s": marks[1][1]}]
    assert not live.feed(kit.noise(0.05))[0]
    text = format_backtest_report(rep)
    assert "找到 2 处" in text and "人工水花 2 段" in text


def test_backtest_requires_template_and_reports_empty(kit):
    with pytest.raises(RuntimeError):
        backtest_recording(kit.noise(0.5), kit.SR, TemplateMatcher(samplerate=kit.SR), [])
    rep = backtest_recording(kit.noise(0.5), kit.SR, _matcher(kit), [])
    assert rep["hits"] == [] and rep["summary"]["n_hits"] == 0
    assert "整段无超过阈值的匹配" in format_backtest_report(rep)
