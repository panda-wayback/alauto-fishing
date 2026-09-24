# src/autofish/detect/ 功能说明

更新时间：2026-09-25

## 本文件夹职责

段3：订 Frame → 识别绿条/鱼漂 → 发 Pos（不改 mss）。方案见 `docs/autofish/detect/`。

## 目录清单

- `api.py` — `BarDetector` / `detect` / `get_detector` / `apply_manual_bar`
- `bobber.py` — `BobberHit` / `pixel_to_pos` / `green_zone_mask`
- `find_bobber.py` — `FindBobber` / `BobberLoc`（独立定漂）
- `bobber_anchor.py` — `BobberAnchorDetector`（先漂后端帽锁条）
- `worker.py` — `DetectorWorker`
- `check_find_bobber_baseline.py` — 定漂基线回归 CLI

## 对外契约

- `detect(rgb) -> BobberHit | None`；默认唯一识别器 `BobberAnchorDetector`
- `apply_manual_bar(box|None)` — 注入/清除手动条界
- `DetectorWorker.start/stop` — 订 Frame；积压帧抛弃不识；已开算帧算完仍发 Pos
- `BobberHit` / `PosEvent.detect_ms` — 单帧耗时随读数发出
- `FindBobber` — 供 bobber_anchor 调用；`python -m autofish.detect.check_find_bobber_baseline`

## 约束

- 禁止发布/缩小/改写 ROI；手框唯一决定 mss。
- 识别线程单帧异常不得退出；监控重启须 `reset_pos_seq`。
- bobber_anchor：入图等比压入 800×800 再映回；有条后条内跟漂；有漂无条仍回报漂位（pos 空）；`≥20fps`。
- find_bobber：宁可 miss 不可错；命中锁档。
- 禁止依赖 `sim` / `algo` / `act`。
