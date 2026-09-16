# src/autofish/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

真机自动拉鱼实现，与 `docs/autofish/` 五段对齐。

## 目录清单

- `locate/` — 段1 手框 ROI（存盘 + 同步 mss）
- `capture/` — 段2 按手框 ROI mss 截帧
- `detect/` — 段3 手框画面内绿+5% 找白 → Pos（**不改 mss**）
- `decide/` — 段4 策略
- `act/` — 段5 真鼠标
- `topics.py` / `bus.py` / `fishing_fsm.py` / `pipeline.py` / `worker_base.py`
- `preview.py` — CLI（`--ui` → `tools.preview_app`）

## 对外契约

- `AutofishPipeline` — `start_monitor` / `start_decide` / `start_act` 及对应 stop
- `Topic.ACTION_INTENT` / `ActionIntentEvent`
- `DecideWorker` / `ActWorker` / `ThresholdPosPolicy`
- 总线：`roi` = 手框 = mss 范围；Detect 不发布 ROI

## 约束

- 手框唯一决定 mss；Detect 只读数，禁止缩/改 ROI。
- Detect：绿+5% 找白；订 Frame；不做模板定框 / 吸色。
- 壳订 Frame（画面）+ Pos（读数）。
- Decide 不点鼠标；Act 不决策。
- 禁止依赖 `sim` / `ui` / `algo`。
- 行为以 `docs/autofish/` 为准。
