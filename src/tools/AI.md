# src/tools/ 功能说明

更新时间：2026-09-24

## 本文件夹职责

调试壳（**PySide6**）：主控干净（A/B 勾选）+ 分页面；同一窗可切**紧凑态**看运行阶段。视觉：柔暗仪表（见 `docs/autofish/shell/`）。

## 目录清单

- `preview_app.py` — 调试壳主窗（完整态 ↔ 紧凑态；导航/管线/持久化）
- `main_page.py` — 主控页 builder
- `calibrate_page.py` — 拉漂配置页 builder（ROI / MONITOR / BAR / 策略）
- `more_page.py` — 更多页 builder（权限 / 开钓时间 / 打包默认）
- `image_canvas.py` — MONITOR 画布 + 漂/条叠层
- `sound_panel.py` — 开钓配置：设备 / 监听 / 模板 / 阈值 / 实时波形
- `backtest_panel.py` — 回测：长录音 / 会话 / 模板库 / 波形
- `template_combo.py` — 模板下拉填充（开钓页与回测页共用）
- `busy_worker.py` — 后台任务线程 + 等待条
- `shell_log.py` — 各页本地日志（最新在上）
- `status_hud.py` — `StatusHudPanel`（紧凑态内容：阶段灯 + 主界面）
- `macos_overlay.py` — macOS 抬窗层级 / 加入全屏 Space（紧凑态叠游戏）
- `shell_theme.py` — 柔暗色板 + `global_qss()` / `preview_canvas_qss()`
- `shell_config.py` — 用户 `data/shell_settings.json` + 打包默认 `assets/shell_settings.json`；「写入打包默认」
- `bar_mark_canvas.py` — 条界参考图 + 程序/手动竖线
- `dual_range_axis.py` — 策略双区间数轴；`SingleRangeBar` 单段可拖（开钓等待/长按）
- `first_click_trigger_window.py` — 兼容再导 `FirstClickTriggerPanel` / `AudioBacktestPanel`
- `waveform_select.py` — 回测波形长条

## 对外契约

- `PreviewApp`：一窗两态；主控「浮窗」→ 紧凑；紧凑「主界面」→ 完整
- 紧凑态：阶段灯（听声/触发/开局/拉松漂/结束）；不另开独立 Tool 窗
- 持久化：用户 `data/shell_settings.json`；打包默认 `assets/shell_settings.json`（更多页可写入）；A/B、设备名、开钓等待/长按、完整窗几何、阈值/策略/间隔/置顶、`compact_mode`；模板→`active.json`；ROI→既有存盘
- 浮窗：就地缩小/放大（不跨屏瞬移）；启动已是紧凑时才用上次拖动落点
- 有 ROI：Capture/Detect 常开；B=Decide+Act；A=会话机

## 约束

- 允许依赖 `autofish` / PySide6；壳内不再嵌模拟器。
- 禁止实现五段业务。
