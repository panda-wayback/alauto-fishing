# src/tools/ 功能说明

更新时间：2026-09-22

## 本文件夹职责

调试壳（**PySide6**）：主控干净（A/B 勾选）+ 分页面；同一窗可切**紧凑态**看运行阶段。视觉：柔暗仪表（见 `docs/autofish/shell/`）。

## 目录清单

- `preview_app.py` — 调试壳主窗（完整态 ↔ 紧凑态；`mode_stack`）
- `status_hud.py` — `StatusHudPanel`（紧凑态内容：阶段灯 + 主界面）
- `macos_overlay.py` — macOS 抬窗层级 / 加入全屏 Space（紧凑态叠游戏）
- `shell_theme.py` — 柔暗色板 + `global_qss()` / `preview_canvas_qss()`
- `shell_config.py` — `ShellSettings`（A/B、设备名、完整窗几何、阈值/策略/间隔/置顶、`compact_mode` / 紧凑落点）
- `bar_mark_canvas.py` — 条界参考图 + 程序/手动竖线
- `dual_range_axis.py` — 策略双区间数轴
- `first_click_trigger_window.py` — 开钓配置 + 回测面板
- `waveform_select.py` — 回测波形长条

## 对外契约

- `PreviewApp`：一窗两态；主控「浮窗」→ 紧凑；紧凑「主界面」→ 完整
- 紧凑态：阶段灯（听声/触发/开局/拉松漂/结束）；不另开独立 Tool 窗
- 持久化：`compact_mode` + 紧凑落点；A/B；音频设备名；完整窗几何；阈值/策略/间隔/置顶；模板→`active.json`；ROI→既有存盘；缺省阈值 **0.70**；A 默认关 / B 默认开；启动默认完整态
- 浮窗：就地缩小/放大（不跨屏瞬移）；启动已是紧凑时才用上次拖动落点
- 有 ROI：Capture/Detect 常开；B=Decide+Act；A=会话机

## 约束

- 允许依赖 `autofish` / PySide6；壳内不再嵌模拟器。
- 禁止实现五段业务。
