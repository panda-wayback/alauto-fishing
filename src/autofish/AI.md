# src/autofish/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

真机自动拉鱼实现，与 `docs/autofish/` 五段对齐。

## 目录清单

- `locate/` — 段1 圈定范围（ROI、LocatorWorker）
- `capture/` — 段2 mss 截图（screen、CaptureWorker）
- `detect/` — 段3 识别（bobber、平滑、吸色、DetectorWorker）
- `decide/` — 段4 算法判定（未实现）
- `act/` — 段5 执行（未实现）
- `topics.py` / `bus.py` / `fishing_fsm.py` / `pipeline.py` / `worker_base.py` — 域总线与串接
- `preview.py` — CLI（无头调试图；`--ui` 转调 `tools.preview_app`）

## 对外契约

- `AutofishPipeline` — 启停；`subscribe` / `snapshot` / `set_roi_manual` / `locate_now`
- `AutofishBus` — 域总线（内部 `common.pubsub.EventBus`）
- `Topic` / `FishingState` — 主题与钓鱼状态
- `Roi` / `grab_roi` / `find_bobber` — 段内原语

## 约束

- 依赖 `common.pubsub`；**禁止**依赖 `sim` / `ui` / `algo`。
- 预览窗在 `src/tools/`，不在本包。
- 行为以 `docs/autofish/` 为准。
