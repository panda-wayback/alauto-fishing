"""预览：截 ROI（或读图）→ 色块 → 写出调试图。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from autofish.detect.api import detect
from autofish.detect.bobber import BobberHit, green_zone_mask
from autofish.capture.screen import grab_roi
from autofish.locate.roi import DEFAULT_ROI_PATH, load_roi


def _save_preview(rgb: np.ndarray, out: Path) -> BobberHit | None:
    from PIL import Image

    hit = detect(rgb)
    mask = green_zone_mask(rgb) > 0
    vis = rgb.copy()
    vis[mask] = np.clip(vis[mask].astype(np.int16) + (0, 60, 0), 0, 255).astype(np.uint8)
    if hit is not None:
        x, y = int(hit.x), int(hit.y)
        vis[max(0, y - 2) : y + 3, max(0, x - 2) : x + 3] = (0, 255, 255)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(vis).save(out)
    return hit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="预览张力条 ROI 色块跟漂")
    parser.add_argument(
        "--roi",
        type=Path,
        default=DEFAULT_ROI_PATH,
        help=f"ROI json（默认 {DEFAULT_ROI_PATH}）",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="可选：用本地 RGB 图代替 mss（调试）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/debug_bobber.png"),
        help="调试输出图",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="打开分区预览窗（推荐）",
    )
    args = parser.parse_args(argv)

    if args.ui:
        from PySide6.QtWidgets import QApplication, QStyleFactory
        from tools.preview_app import PreviewApp

        app = QApplication.instance() or QApplication(sys.argv)
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            app.setStyle(fusion)
        win = PreviewApp(roi_path=args.roi)
        win.show()
        return app.exec()

    if args.image is not None:
        from PIL import Image

        rgb = np.asarray(Image.open(args.image).convert("RGB"), dtype=np.uint8)
    else:
        if not args.roi.exists():
            print(f"缺少 ROI 文件：{args.roi}", file=sys.stderr)
            print("请先写入 data/roi.json，例如：", file=sys.stderr)
            print(
                '  {"left": 100, "top": 800, "width": 820, "height": 101}',
                file=sys.stderr,
            )
            return 1
        rgb = grab_roi(load_roi(args.roi))

    hit = _save_preview(rgb, args.out)
    if hit is None:
        print(f"未找到鱼漂色块 → {args.out}")
        return 2
    print(
        f"pos={hit.pos:.1f}  (0~100)  x={hit.x:.1f} y={hit.y:.1f} "
        f"pixels={hit.pixel_count} → {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
