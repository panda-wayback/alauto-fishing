# src/autofish/act/ 功能说明

更新时间：2026-09-22

## 本文件夹职责

段5：订 ActionIntent → 系统鼠标按下/松开。方案见 `docs/autofish/act/`。

## 目录清单

- `mouse.py` — `MouseActuator`（pynput）
- `worker.py` — `ActWorker`（订意图 + 按下间隔 + 订会话松手）

## 对外契约

- `ActWorker.start/stop/poll` — 订意图；A 关时鱼漂 `FISHING` 控鼠，A 开时仅会话 `FISHING`；进 `FIRST_CLICK` 等非拉漂会话立刻松本段键；单帧无 Pos 不松；系统让位仅在有权控鼠时
- `ActWorker.pressed` / `yielding` / `press_interval` — 程序是否按下；是否让位；当前按下间隔
- `Topic.PRESS_INTERVAL` / `PressIntervalEvent` — 壳发布，Act 订阅（0～0.3s，默认 0）
- `os_left_down()` / `MouseActuator.set_holding` / `force_release`

## 约束

- 只跟意图，不决策；落点=当前光标。
- 两次程序按下受 `press_interval` 门控；松开立刻。
- 依赖 `pynput`；macOS 需辅助功能；Windows 用 `GetAsyncKeyState` 读键态。
