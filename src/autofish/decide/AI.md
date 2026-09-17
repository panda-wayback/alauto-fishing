# src/autofish/decide/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

段4：订 Pos → 范围抽样阈值策略 → 发 ActionIntent。方案见 `docs/autofish/decide/`。

## 目录清单

- `policy.py` — `ThresholdPosPolicy`（范围抽样；切换成功后重抽；最短切换间隔默认 0.1s）
- `worker.py` — `DecideWorker`（`set_ranges` / `current_thresholds`）

## 对外契约

- `DecideWorker.start/stop` — 订阅/退订；`FISHING` 下单帧无 Pos 保持意图；离开钓鱼态才松
- `DecideWorker.set_ranges(press_lo, press_hi, release_lo, release_hi)`
- `DecideWorker.current_thresholds` → `(low, high)`
- `ThresholdPosPolicy.decide(pos, t) -> (holding, reason)`

## 约束

- 不截屏、不识图、不点鼠标。
- 不依赖 `sim` / `algo`（规则同型，实现自洽）。
