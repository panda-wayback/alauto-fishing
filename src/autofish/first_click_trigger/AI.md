# src/autofish/first_click_trigger/ 功能说明

更新时间：2026-09-25

## 本文件夹职责

声音开钓会话机：听水花 → 第一下 → 等漂 → 拉鱼会话。方案见 `docs/autofish/first_click_trigger/`。

## 目录清单

- `audio_input.py` — 采集（Win：soundcard 环回；mac：sounddevice 虚拟输入）；长录音
- `ring_buffer.py` — 最近 20s 循环缓冲（开钓页波形）
- `template_matcher.py` — Mel + 双后缀窗 + 抬升门控
- `session_eval.py` — 长录音落盘 / 回测 / 区间抽模板
- `paths.py` — 用户库与内置模板、会话目录、`active.json`
- `trigger.py` — `FirstClickTrigger` 会话机
- 壳侧：`tools/sound_panel.py` / `backtest_panel.py` / `waveform_select.py`

## 对外契约

- `FirstClickTrigger` — 挂总线发 `CAST_SESSION`、订 Pos；模板加载/选区入库；试听
- 会话：`WAIT` →（命中）`FIRST_CLICK` → `WAIT_BOBBER` → `FISHING` →（丢漂）`WAIT`
- `SplashHit` 随进 `FIRST_CLICK` 的会话事件带出
- `paths.resolve_template_path` / 库增删改名；内置默认 Win→`windows.npy` / mac→`macos.npy`
- `session_eval.save_session` / `backtest_recording` / `extract_range`

## 约束

- 仅 `WAIT` 且冷却已过才听声并更新抬升基线；环缓 20s。
- A 关为 `DISABLED`；不订 `ACTION_INTENT`。
- `stop` 先 abort 音频流再 join；匹配慢于实时也不丢块（与回测同源）。
- 禁止依赖 `sim` / `algo` / `ui`。
