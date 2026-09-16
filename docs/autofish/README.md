# 真机自动拉鱼（功能架构）

## 目标

真机自动拉鱼的**功能架构**：按五段拆开，每段只做一件事；段与段经总线交接。与 [`docs/simulator/`](../simulator/) 模拟器分离。不含 YOLO。

## 要实现的

| 段 | 只做什么 | 产出 | 子文档 |
|---|---|---|---|
| **1. 圈定范围** | CV 找绿条区域并框选，得到截图范围（对角点1、点2 → ROI） | 有效 ROI / 无 ROI | [`docs/autofish/locate/`](locate/) |
| **2. 截图** | mss **只**按当前 ROI 持续截帧；**无 ROI 则不截、不监控** | 最新 Frame（有 ROI 时） | [`docs/autofish/capture/`](capture/) |
| **3. 识别** | 只消费 mss 最新图，绿条两端+5% 区间上算出鱼漂 0～100 并发布 | Pos（及钓鱼状态所需读数） | [`docs/autofish/detect/`](detect/) |
| **4. 算法** | 订 Pos，阈值策略产出按住/松开意图 | ActionIntent | [`docs/autofish/decide/`](decide/) |
| **5. 执行** | 订意图，系统级鼠标按下/松开（当前光标） | 键态变化 | [`docs/autofish/act/`](act/) |

约束：

- 主线极简：**手框 → ROI（=监控=CV，不得越框）→ mss → 完整绿条两端各+5% 定 0/100 → 找白**。不做模板 / 吸色。
- 各段不越权：截图不管识别；识别不点鼠标；算法不截屏；执行不做决策。
- 段 1～3 为感知；段 4～5 为决策与执行。串接见 [`docs/autofish/pipeline/`](pipeline/)。
- 手动框选可与段 1 并存，同样只产出 ROI（点1、点2）；手框即监控与识别范围。
- **允许的例外**：Locate 找条可读 Capture 提供的「全屏/主屏一帧」作为输入图；Capture 可依赖公共 `Roi` 类型（不因此承担找条职责）。
- **预览/调试壳**：属 `src/tools/`，**不是**五段之一。只订阅展示；**监控 / 策略 / 操作** 三开关独立；操作默认关。模拟器独立（见 `docs/simulator/`），壳禁止把 Act 状态写入模拟器。本轮不换 PySide6。**监控显示原画面**；叠层仅标鱼漂命中（禁止绿→灰；禁止青框/青缘干扰读数）。
- 代码：`src/autofish/{locate,capture,detect,decide,act}/`；总线 `src/common/pubsub/`。

失败（总览）：任一段失败不得由其他段「顺手修补」职责；应回到该段或清空 ROI / 停止执行。

## 解决步骤

1. 五段分工与子文档架子（已完成；目录由 `vision` 更名为 `autofish`）。
2. 订阅串接 → [`docs/autofish/pipeline/`](pipeline/)。
3. Locate / Detect / Decide / Act 契约已写入并对齐实现。
4. 调试壳解耦与三开关、读数提频（已完成）。
