# src/common/ 功能说明

更新时间：2026-09-26

## 本文件夹职责

无业务通用库。方案见 `docs/common/`。

## 目录清单

- `pubsub/` — 进程内 EventBus → `pubsub/AI.md`
- `paths.py` — `bundle_root` / `data_root` / `assets_dir`（源码与冻结）
- `permissions.py` — 截屏/控鼠权限状态与授权引导（macOS + Windows）
- `expire.py` — 打包过期日；`is_expired` / `try_self_delete`（方案见 `docs/autofish/expire/`）
- `license.py` — 密钥验签 / license 读写；与 expire 独立（方案见 `docs/autofish/license/`）

## 对外契约

- 经子包导出（如 `common.pubsub.EventBus`）。
- `common.paths.bundle_root` / `data_root` / `assets_dir`（冻结：Windows exe 同级 `data\`，不可写退 LOCALAPPDATA；macOS Application Support）
- `common.permissions.current_status` / `request_screen_access` / `request_input_access` / `reset_macos_tcc` / `restart_as_admin`
- `common.expire.is_expired` / `try_self_delete` / `write_expire_from_days`（构建写 `assets/expire.json`）
- `common.license.issue_key` / `activate_key` / `is_licensed`（`data/license.json`）

## 约束

- 禁止依赖 `autofish` / `sim` / `algo` / UI。
- 权限模块可依赖 `mss`（探测截屏）；禁止业务逻辑。
