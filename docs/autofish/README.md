# 真机自动拉鱼（功能架构）

## 目标

真机自动拉鱼的**功能架构**：按五段拆开，每段只做一件事；段与段经总线交接。与 [`docs/simulator/`](../simulator/) 模拟器分离。不含 YOLO。

## 要实现的

| 段 | 只做什么 | 产出 | 子文档 |
|---|---|---|---|
| **1. 圈定范围** | 手框（或可选找绿）产出**天花板 ROI**并存储；同步为 mss 初始截图范围 | 天花板 ROI / 无 ROI | [`docs/autofish/locate/`](locate/) |
| **2. 截图** | mss **只**按**当前 ROI**持续截帧；无 ROI 则不截 | 最新 Frame | [`docs/autofish/capture/`](capture/) |
| **3. 识别** | 订 ROI+Frame：在手框画面内绿+5% 找白得 0～100；**不改 mss** | Pos | [`docs/autofish/detect/`](detect/) |
| **4. 算法** | 订 Pos，阈值策略产出按住/松开意图 | ActionIntent | [`docs/autofish/decide/`](decide/) |
| **5. 执行** | 订意图，系统级鼠标按下/松开（当前光标） | 键态变化 | [`docs/autofish/act/`](act/) |

约束：

- 主线：**手框（存盘）→ 同步 mss（=手框，不再被 CV 改）→ 截帧 → 绿+5% 找白 → Pos**。定框只靠人选；Detect 不改 mss。
- **规则 A**：手框 = 天花板 = 当前 mss；CV **禁止**缩小或撑大手框。
- 各段不越权：截图不管识别；识别不点鼠标；算法不截屏；执行不做决策。
- 段 1～3 为感知；段 4～5 为决策与执行。串接见 [`docs/autofish/pipeline/`](pipeline/)。
- **允许的例外**：Locate 可读 Capture 主屏一帧；Capture 可依赖公共 `Roi`。
- **预览/调试壳**：属 `src/tools/`，**不是**五段之一。订 Frame（画面）+ Pos（读数）；**监控 / 策略 / 操作** 三开关独立；操作默认关。模拟器独立；壳禁止把 Act 写入模拟器。本轮不换 PySide6。监控原画面；叠层仅标命中。
- 代码：`src/autofish/{locate,capture,detect,decide,act}/`；总线 `src/common/pubsub/`。

失败（总览）：任一段失败不得由其他段「顺手修补」职责；应回到该段或清空 ROI / 停止执行。

## 解决步骤

1. 五段分工与子文档架子（已完成；目录由 `vision` 更名为 `autofish`）。
2. 订阅串接 → [`docs/autofish/pipeline/`](pipeline/)。
3. Locate / Detect / Decide / Act 契约已写入并对齐实现。
4. 调试壳解耦与三开关、读数提频（已完成）。
5. mss 仅随手框；Detect 不改范围（已完成）。
