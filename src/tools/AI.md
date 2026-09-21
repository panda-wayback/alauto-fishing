# src/tools/ 功能说明

更新时间：2026-09-22

## 本文件夹职责

调试壳（**PySide6**）：主控干净（A/B 勾选）+ 分页面（自动拉漂配置 / 声音开钓配置 / 回测 / 更多）；各页本地日志（最新在上）。视觉：**柔暗仪表**（见 `docs/autofish/shell/`）。

## 目录清单

- `preview_app.py` — 调试壳主窗 UI（`QStackedWidget`：主控|拉漂配置|开钓配置|回测|更多）
- `shell_theme.py` — 柔暗色板 + `global_qss()` / `preview_canvas_qss()`
- `shell_config.py` — `ShellSettings` 读写 `data/shell_settings.json`
- `bar_mark_canvas.py` — 条界参考图 + 程序/手动竖线（手动可拖）
- `dual_range_axis.py` — 策略双区间数轴（拖动；不重叠；间隔≥1；精度 0.1）
- `first_click_trigger_window.py` — `FirstClickTriggerPanel`（开钓配置）+ `AudioBacktestPanel`（回测）
- `waveform_select.py` — 回测波形长条（绿标注 / 橙命中）

## 对外契约

- `PreviewApp`（QMainWindow）；窗标题产品名；全局 QSS 来自 `shell_theme`
- 布局：导航五页（短标 + tooltip 全称）；日志分层（禁止跨页转发；最新在上）
  - **主控**：A/B、游戏开始/结束（看鱼漂）、声音触发（相似/间隔/按住/阈值）
  - **自动拉漂配置**：ROI/条界提示、开始/结束拉漂（pos+配置）、策略应用
  - **声音开钓配置 / 回测**：各自面板本地日志
  - **更多**：无独立日志区
- **主控**：自动拉漂（B）+ 声音开钓（A）为开关行；精简 POS/会话/键态；**无监控开关**
- **自动拉漂配置**：ROI；MONITOR；BAR；策略数轴；按下间隔；本页日志；主/次/幽灵按钮
- **声音开钓配置**：设备、监听、当前模板、播放、阈值；本页本地日志
- **回测**：长录音、会话、模板库、波形回测；本页本地日志
- **更多**：权限、窗口置顶
- 持久化：`data/shell_settings.json`（阈值、策略区间、按下间隔、置顶）；缺省阈值 **0.70**
- 有 ROI：Capture/Detect **常开**；框选只改范围
- B 开 = Decide + Act；A 开 = 会话机（见 `docs/autofish/first_click_trigger/`）
- 默认：B 开、A 关
- 策略数轴默认 U(70.6～74.4)/U(76.6～79.2)；按下间隔 0～0.3s（默认 0）
- ROI 存盘 `source`：`manual` | `default`
- 监控叠层：有漂画漂，有条画框；UI ≤15fps
- BAR：有漂即出参考图；蓝=程序、黄=手动
- POS：无漂 / 有漂·无条 / 数值

## 约束

- 允许依赖 `autofish` / PySide6；壳内**不再嵌模拟器**。
- 禁止实现五段业务。
