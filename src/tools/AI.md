# src/tools/ 功能说明

更新时间：2026-09-21

## 本文件夹职责

调试壳（**PySide6**）：主控干净（A/B 勾选）+ 分页面（标定 / 声音 / 更多）；底栏日志。无快捷键。

## 目录清单

- `preview_app.py` — 调试壳主窗 UI（`QStackedWidget`：主控|标定|声音|更多）
- `bar_mark_canvas.py` — 条界参考图 + 程序/手动竖线（手动可拖）
- `dual_range_axis.py` — 策略双区间数轴（拖动；不重叠；间隔≥1；精度 0.1）
- `first_click_trigger_window.py` — `FirstClickTriggerPanel`（声音页嵌入）

## 对外契约

- `PreviewApp`（QMainWindow）
- 布局：导航四页 + **主控页内日志**（状态区下方，占满剩余高度）
- **主控**：自动拉漂（B）+ 声音开钓（A）+ 精简 POS/会话/键态 + 日志；**无监控开关**
- **标定**：ROI 框选/重框/恢复默认；MONITOR；BAR
- **声音**：设备、监听、标记/播放/模板、阈值、会话态细项
- **更多**：权限、策略数轴、按下间隔
- 有 ROI：Capture/Detect **常开**；框选只改范围
- B 开 = Decide + Act；A 开 = 会话机（见 `docs/autofish/first_click_trigger/`）
- 默认：B 开、A 关；窗约 440×780
- 策略数轴默认 U(70.6～74.4)/U(76.6～79.2)；按下间隔 0～0.3s（默认 0）
- 配色：默认浅色（白底）
- ROI 存盘 `source`：`manual` | `default`
- 监控叠层：有漂画漂，有条画框；UI ≤15fps
- BAR：有漂即出参考图；蓝=程序、黄=手动
- POS：无漂 / 有漂·无条 / 数值

## 约束

- 允许依赖 `autofish` / PySide6；壳内**不再嵌模拟器**。
- 禁止实现五段业务。
