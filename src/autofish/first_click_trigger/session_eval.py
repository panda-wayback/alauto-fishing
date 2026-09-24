"""长录音会话：落盘、整段查找回测、可选对照标注、从区间截取模板。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

    from autofish.first_click_trigger.template_matcher import TemplateMatcher


@dataclass
class SessionPaths:
    root: Path
    audio: Path
    meta: Path
    marks: Path


def new_session_dir() -> SessionPaths:
    from autofish.first_click_trigger.paths import user_audio_sessions_dir

    root = user_audio_sessions_dir() / datetime.now().strftime("session_%Y%m%d_%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    return SessionPaths(
        root=root,
        audio=root / "audio.npy",
        meta=root / "meta.json",
        marks=root / "marks.json",
    )


def normalize_ranges(
    ranges: list[tuple[float, float]] | list[dict[str, float]],
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for item in ranges:
        if isinstance(item, dict):
            a = float(item["start_s"])
            b = float(item["end_s"])
        else:
            a, b = float(item[0]), float(item[1])
        if b < a:
            a, b = b, a
        if b - a < 1e-3:
            continue
        out.append((a, b))
    out.sort(key=lambda x: x[0])
    return out


def save_session(
    wave: "npt.NDArray[np.float32]",
    samplerate: int,
    ranges: list[tuple[float, float]] | list[dict[str, float]],
    *,
    paths: SessionPaths | None = None,
) -> SessionPaths:
    """audio.npy 存原始采集（多声道为 (N, ch)），回测读取时再转单声道。"""
    paths = paths or new_session_dir()
    paths.root.mkdir(parents=True, exist_ok=True)
    raw = np.asarray(wave, dtype=np.float32)
    np.save(paths.audio, raw)
    frames = int(raw.shape[0])
    meta = {
        "samplerate": int(samplerate),
        "samples": frames,
        "channels": int(raw.shape[1]) if raw.ndim > 1 else 1,
        "duration_s": float(frames / max(samplerate, 1)),
    }
    paths.meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    save_marks(paths, ranges)
    return paths


def save_marks(
    paths: SessionPaths,
    ranges: list[tuple[float, float]] | list[dict[str, float]],
) -> None:
    """只改标注，不动 audio.npy。"""
    norm = normalize_ranges(ranges)
    marks = {
        "splash_ranges": [{"start_s": a, "end_s": b} for a, b in norm],
    }
    paths.marks.write_text(json.dumps(marks, ensure_ascii=False, indent=2), encoding="utf-8")


def load_session_raw(root: Path) -> tuple["npt.NDArray[np.float32]", int]:
    """原始采集（播放原声用）。"""
    raw = np.load(root / "audio.npy").astype(np.float32)
    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    return raw, int(meta["samplerate"])


def load_session(
    root: Path,
) -> tuple["npt.NDArray[np.float32]", int, list[tuple[float, float]]]:
    audio_p = root / "audio.npy"
    meta_p = root / "meta.json"
    marks_p = root / "marks.json"
    wave = np.load(audio_p).astype(np.float32)
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    sr = int(meta["samplerate"])
    ranges: list[tuple[float, float]] = []
    if marks_p.is_file():
        data = json.loads(marks_p.read_text(encoding="utf-8"))
        ranges = normalize_ranges(data.get("splash_ranges", []))
    return wave, sr, ranges


def extract_range(
    wave: "npt.NDArray[np.float32]",
    samplerate: int,
    start_s: float,
    end_s: float,
) -> "npt.NDArray[np.float32]":
    """按用户自选区间截取（不做额外扩窗）。"""
    if end_s < start_s:
        start_s, end_s = end_s, start_s
    i0 = max(0, int(start_s * samplerate))
    i1 = min(len(wave), int(end_s * samplerate))
    if i1 <= i0:
        raise ValueError("区间无效或超出录音范围")
    return np.asarray(wave[i0:i1], dtype=np.float32).copy()


def backtest_recording(
    wave: "npt.NDArray[np.float32]",
    samplerate: int,
    matcher: "TemplateMatcher",
    ranges: list[tuple[float, float]] | list[dict[str, float]],
    *,
    block: int = 1024,
) -> dict[str, Any]:
    """
    独立匹配器滑过整段（不与实时监听抢状态）。
    命中时刻按 feed + 抬升门控；展示分数为该区间峰值 Mel 相似。
    若有对照标注：命中落在标注内 → 真阳；否则假阳；无命中的标注 → 漏检。
    """
    wave = np.asarray(wave, dtype=np.float32)
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    if not matcher.has_template:
        raise RuntimeError("回测需要已加载模板")

    mark_ranges = normalize_ranges(ranges)
    # 独立匹配器：实时监听线程仍在 feed 同一实例时，回测结果会抖动
    offline = matcher.clone_for_offline()
    offline.reset_buffer()
    tpl_s = float(getattr(offline, "template_duration_s", 0.5) or 0.5)
    hits: list[dict[str, float]] = []
    for i in range(0, len(wave), block):
        chunk = wave[i : i + block]
        if chunk.size == 0:
            break
        trig, score = offline.feed(chunk)
        if trig:
            t = (i + chunk.size) / float(samplerate)
            end_s = float(t)
            start_s = max(0.0, end_s - tpl_s)
            hits.append(
                {
                    "t_s": end_s,
                    "score": float(score),
                    "start_s": start_s,
                    "end_s": end_s,
                }
            )
            offline.bump_score_baseline(float(score))

    raw_n = len(hits)
    hits = merge_nearby_hits(hits, merge_gap_s=0.5)
    # 分数改为区间峰值 Mel 相似（非「抬升瞬间」），同录音多次回测应一致
    for h in hits:
        i0 = max(0, int(float(h["start_s"]) * samplerate))
        i1 = min(len(wave), int(float(h["end_s"]) * samplerate))
        if i1 <= i0:
            continue
        peak = float(offline.analyze_clip(wave[i0:i1])["score"])
        h["trigger_score"] = float(h["score"])
        h["score"] = peak

    used = [False] * len(mark_ranges)
    tp: list[dict[str, float]] = []
    fp: list[dict[str, float]] = []
    for h in hits:
        best_j = -1
        for j, (a, b) in enumerate(mark_ranges):
            if used[j]:
                continue
            if a <= h["t_s"] <= b:
                best_j = j
                break
        if best_j >= 0:
            used[best_j] = True
            a, b = mark_ranges[best_j]
            tp.append({**h, "range_start_s": a, "range_end_s": b})
        else:
            fp.append(h)
    fn_ranges = [mark_ranges[j] for j, u in enumerate(used) if not u]

    return {
        "duration_s": float(len(wave) / max(samplerate, 1)),
        "ranges": [{"start_s": a, "end_s": b} for a, b in mark_ranges],
        "hits": hits,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative_ranges": [
            {"start_s": a, "end_s": b} for a, b in fn_ranges
        ],
        "summary": {
            "n_marks": len(mark_ranges),
            "n_hits": len(hits),
            "n_raw_hits": raw_n,
            "tp": len(tp),
            "fp": len(fp),
            "fn": len(fn_ranges),
        },
    }


def merge_nearby_hits(
    hits: list[dict[str, float]],
    *,
    merge_gap_s: float = 0.5,
) -> list[dict[str, float]]:
    """近邻重复触发合并：按分数从高到低保留，间隔 < merge_gap_s 的丢掉。"""
    if not hits:
        return []
    gap = max(0.05, float(merge_gap_s))
    ordered = sorted(hits, key=lambda h: float(h["score"]), reverse=True)
    kept: list[dict[str, float]] = []
    for h in ordered:
        t = float(h["t_s"])
        if any(abs(t - float(k["t_s"])) < gap for k in kept):
            continue
        kept.append(h)
    return sorted(kept, key=lambda h: float(h["t_s"]))


def format_backtest_report(result: dict[str, Any]) -> str:
    """回测报告：命中时刻 + 相似度（波形上另有橙色区间）。"""
    s = result["summary"]
    raw = int(s.get("n_raw_hits", s["n_hits"]))
    merge_note = ""
    if raw > s["n_hits"]:
        merge_note = f"（原始触发 {raw} → 合并近邻后 {s['n_hits']}）"
    lines = [
        f"回测 {result['duration_s']:.1f}s · 找到 {s['n_hits']} 处{merge_note}"
        + (f" · 人工水花 {s['n_marks']} 段" if s["n_marks"] else "")
    ]
    if not result["hits"]:
        lines.append("  （整段无超过阈值的匹配）")
    else:
        for h in sorted(result["hits"], key=lambda x: float(x["t_s"])):
            a = float(h.get("start_s", h["t_s"]))
            b = float(h.get("end_s", h["t_s"]))
            lines.append(
                f"  [{a:.2f},{b:.2f}]s  相似 {h['score']:.2f}"
            )
    lines.append("  （绿=人工水花 · 橙=回测命中，看波形）")
    return "\n".join(lines)
