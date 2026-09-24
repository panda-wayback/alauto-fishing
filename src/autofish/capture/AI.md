# src/autofish/capture/ 功能说明

更新时间：2026-09-25

## 本文件夹职责

段2：按当前手框 ROI 用 mss 截帧并发布 Frame。方案见 `docs/autofish/capture/`。

## 目录清单

- `screen.py` — `grab_roi` / `grab_primary` / `save_screen` / `load_screen` / `warmup`
- `worker.py` — `CaptureWorker`（订 ROI，按 fps 发 Frame）

## 对外契约

- `CaptureWorker.start/stop` — 订 ROI；无 ROI 不截
- `grab_roi(roi) -> RGB`；`warmup()` 冷启动预热
- `grab_primary` / `save_screen` / `load_screen` / `DEFAULT_SCREEN_PATH` — 壳手框标定用
- `ScreenGrab` — 主屏抓取载荷

## 约束

- `mss` 每线程独立实例（Windows 禁止跨线程复用同一 sct）。
- 帧宽高 = 手框；不改 ROI、不识图、不点鼠标。
- 依赖 `locate.Roi`；禁止依赖 `detect` / `decide` / `act`。
