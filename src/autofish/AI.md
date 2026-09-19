# src/autofish/ 功能说明

更新时间：2026-09-19

## 本文件夹职责

真机自动拉鱼实现，与 `docs/autofish/` 五段对齐。

## 目录清单

- `locate/` — 段1 手框 ROI（存盘 + 可选手动条界 bar_* + 同步 mss）
- `capture/` — 段2 按手框 ROI mss 截帧
- `detect/` — 段3 可替换识别器（默认 bobber_anchor）→ Pos（**不改 mss**）
- `decide/` — 段4 策略
- `act/` — 段5 真鼠标
- `topics.py` / `bus.py` / `fishing_fsm.py` / `pipeline.py` / `worker_base.py`
- `preview.py` — CLI（`--ui` → `tools.preview_app`）

## 对外契约

- `AutofishPipeline` — `start_monitor` / `start_decide` / `start_act` 及对应 stop
- `Topic.ACTION_INTENT` / `ActionIntentEvent`
- `Topic.PRESS_INTERVAL` / `PressIntervalEvent`
- `DecideWorker` / `ActWorker` / `ThresholdPosPolicy`
- 总线：`roi` = 手框 = mss 范围；Detect 不发布 ROI

## 约束

- 手框唯一决定 mss；Detect 只读数，禁止缩/改 ROI。
- Capture：`mss` 每线程独立实例（Windows 禁止跨线程复用同一 sct）。
- Detect：霓虹绿核定条 → 两侧橘黄扩展定界（color_blocks）；或先漂后端帽（bobber_anchor 默认）；绿条既定必有漂（白/孔/绿密度谷，候选质心须在条框内，color_blocks）；识别线程异常不退出；监控重启重置帧序
- Detect 计时：`PosEvent.detect_ms` = 单帧识别耗时；壳显示 + 每 2s 日志
- template 识别器：模板构造时加载一次并缓存多尺度；压缩灰度匹配 + 上一位置跟踪；模板须与实机同比例
- color_blocks 识别器（可选）：入图过宽先等比压缩定条、坐标映回；漂在原图像素条框附近找；每帧 HSV/RGB 通道只算一次给四掩膜共用；`use_color_blocks()` 切换
- bobber_anchor 识别器（默认）：先准确定漂 → 手动/自动锁条 → 有条后只在条内跟漂；条内尺度用上一帧或**条高**估（禁止用邻域高）；**有漂无条仍回报漂位**（pos 空）；整段 ≥20fps；`use_bobber_anchor()` / `apply_manual_bar`
- find_bobber（独立）：颜色结构（须羽冠+红箍+亮肚）+ 小 ROI 彩色复核；门槛偏严；可传条邻域只在条内搜；宁可 miss 不可错
- 壳订 Frame（画面）+ Pos（读数）。
- Decide 不点鼠标；Act 不决策。
- 禁止依赖 `sim` / `ui` / `algo`。
- 行为以 `docs/autofish/` 为准。
