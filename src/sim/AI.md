# src/sim/ 功能说明

更新时间：2026-09-25

## 本文件夹职责

拉鱼模拟纯逻辑。方案见 `docs/simulator/`。

## 目录清单

- `game.py` — 状态机与物理
- `api.py` — 观测 / `step(holding)`
- `difficulty.py` — T1–T8
- `config.py` — 参数与资源路径

## 对外契约

- `FishingGame` / `observe` / `step` — 见 `api.py`
- 不依赖 pygame / `autofish`

## 约束

- 禁止依赖 `ui` / `autofish` / `tools`。
