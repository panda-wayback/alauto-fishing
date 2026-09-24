# src/ui/ 功能说明

更新时间：2026-09-25

## 本文件夹职责

模拟器画面拼装（pygame）。

## 目录清单

- `render.py` — 张力条 / 进度条绘制

## 对外契约

- `Renderer` — 根据 `FishingGame` 状态画一帧

## 约束

- 可依赖 `sim`；禁止依赖 `autofish` / `algo` 业务。
