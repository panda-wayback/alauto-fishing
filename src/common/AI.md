# src/common/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

无业务通用库。方案见 `docs/common/`。

## 目录清单

- `pubsub/` — 进程内 EventBus → `pubsub/AI.md`
- `paths.py` — `bundle_root` / `data_root` / `assets_dir`（源码与冻结）
- `permissions.py` — 截屏/控鼠权限状态与授权引导（macOS + Windows）

## 对外契约

- 经子包导出（如 `common.pubsub.EventBus`）。
- `common.paths.bundle_root` / `data_root` / `assets_dir`（冻结：macOS Application Support / Windows LOCALAPPDATA）
- `common.permissions.current_status` / `request_screen_access` / `request_input_access` / `restart_as_admin`

## 约束

- 禁止依赖 `autofish` / `sim` / `algo` / UI。
- 权限模块可依赖 `mss`（探测截屏）；禁止业务逻辑。
