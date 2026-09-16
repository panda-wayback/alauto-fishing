# src/tools/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

调试与编排入口：可组合 `autofish` + `sim` + `ui`。方案上不属于五段流水线。

## 目录清单

- `preview_app.py` — 真机框选/读数预览窗（可并排模拟器）

## 对外契约

- `PreviewApp` — pygame 预览窗；`run()` 进入主循环
- CLI 仍经 `python -m autofish.preview --ui` 打开

## 约束

- 允许依赖 `autofish` / `sim` / `ui`。
- 禁止把业务五段实现写进本包。
