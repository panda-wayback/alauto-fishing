# src/autofish/act/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

段5：订 ActionIntent → 系统鼠标按下/松开。方案见 `docs/autofish/act/`。

## 目录清单

- `mouse.py` — `MouseActuator`（pynput）
- `worker.py` — `ActWorker`

## 对外契约

- `ActWorker.start/stop` — 订阅意图；停时强制松开
- `ActWorker.pressed` — 当前是否按下
- `MouseActuator.set_holding(bool)`

## 约束

- 只跟意图，不决策；落点=当前光标。
- 依赖 `pynput`；macOS 需辅助功能权限。
