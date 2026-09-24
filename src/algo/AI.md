# src/algo/ 功能说明

更新时间：2026-09-25

## 本文件夹职责

策略接口、无头跑局、阈值按住策略。方案见 `docs/simulator/algo-test/`。

## 目录清单

- `base.py` — `PullPolicy` 协议
- `runner.py` — `run_episode` / `run_batch`
- `threshold_hold.py` — 绿区相对 pos<50 按住 / >90 松开 + 切换间隔
- `__main__.py` — CLI 批量入口

## 对外契约

- `ThresholdHoldPolicy` — `decide(obs) -> holding`（模拟器测，不点真鼠标）
- `bobber_pos_in_safe_100(obs)` — 绿区内 0～100
- `python -m algo --tier 4 --episodes 50`

## 约束

- 只依赖 `sim`；禁止依赖 `ui` / `autofish`。
