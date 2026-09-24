# src/autofish/ 功能说明

更新时间：2026-09-25

## 本文件夹职责

真机自动拉鱼实现，与 `docs/autofish/` 五段对齐；另含「声音开钓」会话机。

## 目录清单

- `locate/` — 段1 手框 ROI / 手动条界存盘 → `locate/AI.md`
- `capture/` — 段2 mss 截帧 → `capture/AI.md`
- `detect/` — 段3 识别 → Pos → `detect/AI.md`
- `decide/` — 段4 策略 → 意图 → `decide/AI.md`
- `act/` — 段5 真鼠标 → `act/AI.md`
- `first_click_trigger/` — 声音开钓会话机 → `first_click_trigger/AI.md`
- `topics.py` / `bus.py` — 主题事件与 `AutofishBus` 快照
- `fishing_fsm.py` — 鱼漂 FSM（A 关拉漂态）
- `pipeline.py` — 分段启停编排
- `worker_base.py` — Worker 线程基类
- `preview.py` — CLI（`--ui` → `tools.preview_app`）

## 对外契约

- `AutofishPipeline` — `start_monitor` / `start_decide` / `start_act` 及对应 stop
- `Topic.*` / 各 `*Event`（含 `SplashHit`、`PressIntervalEvent`）
- `DecideWorker` / `ActWorker` / `ThresholdPosPolicy` / `FirstClickTrigger`
- 总线：`roi` = 手框 = mss 范围；Detect 不发布 ROI

## 约束

- 手框唯一决定 mss；Detect 只读数，禁止缩/改 ROI。
- Decide 不点鼠标；Act 不决策。
- Worker：`stop` join 超时不假装线程已死（`is_running` 仍真）。
- 壳订 Frame（画面）+ Pos（读数）。
- 禁止依赖 `sim` / `ui` / `algo`。
- 行为以 `docs/autofish/` 为准；子段细节见各叶子 `AI.md`。
