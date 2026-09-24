# src/autofish/ 功能说明

更新时间：2026-09-21

## 本文件夹职责

真机自动拉鱼实现，与 `docs/autofish/` 五段对齐；另含「声音开钓」会话机。

## 目录清单

- `locate/` — 段1 手框 ROI（存盘 `source=manual|default`；手动优先；无存盘/恢复默认→主屏居中 1/4×1/4；可选手动条界 bar_* + 同步 mss）
- `capture/` — 段2 按手框 ROI mss 截帧
- `detect/` — 段3 可替换识别器（默认 bobber_anchor）→ Pos（**不改 mss**）
- `decide/` — 段4 策略
- `act/` — 段5 真鼠标；A 开时仅会话 `FISHING` 控鼠（第一下/等漂松手），A 关时跟鱼漂 FSM
- `decide/` — 段4；A 开时仅会话 `FISHING` 才发按住意图
- `first_click_trigger/` — 声音开钓（独立 Worker + 会话态）
  - `audio_input.py` — Windows：`soundcard` WASAPI 真环回（系统默认扬声器 Loopback 排首位；采样率=设备实际混音格式 `GetMixFormat`（不重采样，读不到才 44100）/ 2ch / 1024 帧）；macOS：`sounddevice` + 虚拟输入；长录音 `begin_record/end_record` 在采集线程收原始块（不经可丢块检测队列）
  - `ring_buffer.py` — 最近 20 秒循环缓冲；标记按能量截有效段
  - `detector.py` — 能量/频段检测（无模板兜底，默认关）
  - `template_matcher.py` — Mel 帧峰值高分位归一 + 双后缀窗（短 0.8s / 长 2.0s pad）取高分 + 抬升门控；默认阈值 0.70 / 静音 -80dB；STFT 批量向量化
  - `session_eval.py` — 长录音落盘（`audio.npy` 存原始多声道；`load_session` 转单声道回测，`load_session_raw` 供原声试听）、`save_marks` 只改标注、整段查找回测、区间抽模板
  - `paths.py` — 用户库 `audio_template/` + 内置 `assets/audio/*.npy`（默认 Windows→`windows.npy` / macOS→`macos.npy`）；长录音 `audio_sessions/`；冻结包 `seed/` 缺则拷到本机 data
  - `trigger.py` — 会话机；试听走默认扬声器（失败退回 device=None）；听声冷却；按住时长
- `../tools/waveform_select.py` — 回测波形长条（绿人工水花 / 橙回测命中）
- `../tools/sound_panel.py` — 开钓配置页（设备 / 监听 / 模板 / 阈值）
- `../tools/backtest_panel.py` — 回测页面板
- `../tools/first_click_trigger_window.py` — 兼容再导（同上两面板）
- `topics.py` / `bus.py` / `fishing_fsm.py` / `pipeline.py` / `worker_base.py`
- `preview.py` — CLI（`--ui` → `tools.preview_app`）

## 对外契约

- `AutofishPipeline` — `start_monitor` / `start_decide` / `start_act` 及对应 stop
- `Topic.ACTION_INTENT` / `ActionIntentEvent`
- `Topic.PRESS_INTERVAL` / `PressIntervalEvent`
- `Topic.CAST_SESSION` / `CastSessionEvent` / `CastSessionState` / `SplashHit`（命中进 FIRST_CLICK 时带 score/delay/hold/after/threshold）
- `DecideWorker` / `ActWorker` / `ThresholdPosPolicy`
- `FirstClickTrigger` — 可挂总线发会话态、订 Pos；标记模板；播放试听
- 总线：`roi` = 手框 = mss 范围；Detect 不发布 ROI

## 约束

- 手框唯一决定 mss；Detect 只读数，禁止缩/改 ROI。
- Capture：`mss` 每线程独立实例（Windows 禁止跨线程复用同一 sct）。
- Detect：霓虹绿核定条 → 两侧橘黄扩展定界（color_blocks）；或先漂后端帽（bobber_anchor 默认）；绿条既定必有漂（白/孔/绿密度谷，候选质心须在条框内，color_blocks）；识别线程异常不退出；监控重启重置帧序
- Detect 计时：`PosEvent.detect_ms` = 单帧识别耗时；壳显示 + 每 2s 日志（仅近 2s，标条内/全图）
- template 识别器：模板构造时加载一次并缓存多尺度；压缩灰度匹配 + 上一位置跟踪；模板须与实机同比例
- color_blocks 识别器（可选）：入图过宽先等比压缩定条、坐标映回；漂在原图像素条框附近找；每帧 HSV/RGB 通道只算一次给四掩膜共用；`use_color_blocks()` 切换
- bobber_anchor 识别器（默认）：先准确定漂 → 手动/自动锁条 → 有条后只在条内跟漂；入图**等比压入 800×800** 再识、坐标映回；模板档约 0.14～1.0、多试邻近档、**命中锁档**；**无 local**；跟漂 mid≈条长½（夹在 full-nbr 内）；**禁止同帧 mid+full**；mid 丢→隔帧 full-nbr 恢复；邻域**底贴条底、只向上扩**；锁档条内**命中即停**；**监控开关保留程序锁**（ROI 未变）；**有漂无条仍回报漂位**（pos 空）；整段 ≥20fps；`use_bobber_anchor()` / `apply_manual_bar`
- find_bobber（独立）：入图同压 800×800；颜色结构 + 小 ROI 彩色复核；多档邻近/失败扩档；命中锁定尺度；条邻域锁档少档且命中即停；宁可 miss 不可错
- `FirstClickTrigger`：仅 `WAIT` 且冷却已过才听声并更新抬升基线；环缓 20s；开钓页可滚动画波形+命中橙标；立刻进 `FIRST_CLICK`（等待/长按/松开后区间可配置，sleep 可被 stop 打断）→ `WAIT_BOBBER`（3s）→ 出漂 `FISHING` → 丢漂满 1s 回 `WAIT`（再冷却 3s）；失败回 `WAIT`；发布 `CAST_SESSION`；`stop` 先 abort 音频流再 join；`_run` 每轮取完队列积压块再匹配一次（匹配慢于实时也不丢块，与回测同源）
- Worker：`stop` join 超时不假装线程已死（`is_running` 仍真）
- 壳订 Frame（画面）+ Pos（读数）。
- Decide 不点鼠标；Act 不决策。
- 禁止依赖 `sim` / `ui` / `algo`。
- 行为以 `docs/autofish/` 为准。
