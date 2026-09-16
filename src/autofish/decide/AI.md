# src/autofish/decide/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

段4：订 Pos → 阈值策略 → 发 ActionIntent。方案见 `docs/autofish/decide/`。

## 目录清单

- `policy.py` — `ThresholdPosPolicy`（&lt;50 按住 / &gt;90 松开 + 切换间隔）
- `worker.py` — `DecideWorker`

## 对外契约

- `DecideWorker.start/stop` — 订阅/退订；停时发松开意图
- `ThresholdPosPolicy.decide(pos, t) -> (holding, reason)`

## 约束

- 不截屏、不识图、不点鼠标。
- 不依赖 `sim` / `algo`（规则对齐 algo-test，实现自洽）。
