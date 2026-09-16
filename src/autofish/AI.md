# src/autofish/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

真机自动拉鱼实现，与 `docs/autofish/` 五段对齐。

## 目录清单

- `locate/` — 段1 圈定范围
- `capture/` — 段2 mss 截图
- `detect/` — 段3 完整绿条两端+5% → 找白 → 0～100（不越手框）
- `decide/` — 段4 策略
- `act/` — 段5 真鼠标
- `topics.py` / `bus.py` / `fishing_fsm.py` / `pipeline.py` / `worker_base.py`
- `preview.py` — CLI（`--ui` → `tools.preview_app`）

## 对外契约

- `AutofishPipeline` — `start_monitor` / `start_decide` / `start_act` 及对应 stop
- `Topic.ACTION_INTENT` / `ActionIntentEvent`
- `DecideWorker` / `ActWorker` / `ThresholdPosPolicy`

## 约束

- Detect：完整绿条两端各+5% 为 0/100（略含近端橙）；找白；不越 ROI；无模板/吸色/青框。
- 手框 ROI = 监控 = CV；监控原画面，只标命中。
- Decide 不点鼠标；Act 不决策。
- 禁止依赖 `sim` / `ui` / `algo`。
- 行为以 `docs/autofish/` 为准。
