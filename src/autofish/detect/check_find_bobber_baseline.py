"""对照 data/test/find_bobber_baseline.json，防止 find_bobber 回归。

用法（仓库根）:
  PYTHONPATH=src uv run python -m autofish.detect.check_find_bobber_baseline
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

from autofish.detect.find_bobber import FindBobber
from common.paths import bundle_root


def main() -> int:
    root = bundle_root()
    test_dir = root / "data" / "test"
    base_path = test_dir / "find_bobber_baseline.json"
    if not base_path.is_file():
        print(f"缺少基线: {base_path}", file=sys.stderr)
        return 2
    data = json.loads(base_path.read_text(encoding="utf-8"))
    tol = data.get("tolerance", {})
    center_tol = float(tol.get("center_px", 12))
    box_tol = float(tol.get("box_px", 16))
    score_delta = float(tol.get("score_min_delta", -0.05))

    finder = FindBobber()
    failed = 0
    for case in data["cases"]:
        name = case["file"]
        path = test_dir / name
        if not path.is_file():
            print(f"[FAIL] 缺图 {name}")
            failed += 1
            continue
        bgr = cv2.imread(str(path))
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        loc = finder.find(rgb)
        want = case["status"]
        if want == "MISS":
            if loc is not None:
                print(f"[FAIL] {name}: 期望 MISS，实际 HIT @({loc.x:.0f},{loc.y:.0f})")
                failed += 1
            else:
                print(f"[OK]   {name}: MISS")
            continue
        if loc is None:
            print(f"[FAIL] {name}: 期望 HIT，实际 MISS")
            failed += 1
            continue
        dx = abs(loc.x - case["x"])
        dy = abs(loc.y - case["y"])
        dbox = max(
            abs(loc.left - case["left"]),
            abs(loc.top - case["top"]),
            abs(loc.width - case["width"]),
            abs(loc.height - case["height"]),
        )
        score_ok = loc.score >= case["score"] + score_delta
        if dx > center_tol or dy > center_tol or dbox > box_tol or not score_ok:
            print(
                f"[FAIL] {name}: "
                f"中心Δ=({dx:.1f},{dy:.1f}) boxΔ={dbox} "
                f"score={loc.score:.3f} vs {case['score']:.3f}"
            )
            failed += 1
        else:
            print(
                f"[OK]   {name}: @({loc.x:.0f},{loc.y:.0f}) "
                f"sc={loc.score:.3f} {loc.detect_ms:.0f}ms"
            )
    if failed:
        print(f"\n回归失败 {failed} 项", file=sys.stderr)
        return 1
    print(f"\n全部通过（{len(data['cases'])}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
