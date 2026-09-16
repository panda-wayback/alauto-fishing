# 真机自动拉鱼（功能架构）

## 目标

真机自动拉鱼的**功能架构**：按五段拆开，每段只做一件事；段与段经总线交接。与 [`docs/simulator/`](../simulator/) 模拟器分离。不含 YOLO。

## 要实现的

| 段 | 只做什么 | 产出 | 子文档 |
|---|---|---|---|
| **1. 圈定范围** | CV（`matchTemplate` 等）找出张力条，得到截图范围（对角点1、点2 → ROI） | 有效 ROI / 无 ROI | [`docs/autofish/locate/`](locate/) |
| **2. 截图** | mss **只**按当前 ROI 持续截帧；**无 ROI 则不截、不监控** | 最新 Frame（有 ROI 时） | [`docs/autofish/capture/`](capture/) |
| **3. 识别** | 只消费 mss 最新图，色块算出鱼漂 0～100 并记录/发布 | Pos（及钓鱼状态所需读数） | [`docs/autofish/detect/`](detect/) |
| **4. 算法** | 只根据识别结果判定操作（如按住/松开） | 动作意图 | [`docs/autofish/decide/`](decide/) |
| **5. 执行** | 只把动作意图落到真机输入 | 实际按键/鼠标 | [`docs/autofish/act/`](act/) |

约束：

- 各段不越权：截图不管识别；识别不点鼠标；算法不截屏；执行不做决策。
- 段 1～3 为感知；段 4～5 为决策与执行。串接见 [`docs/autofish/pipeline/`](pipeline/)。
- 手动框选可与段 1 并存，同样只产出 ROI（点1、点2）。
- **允许的例外**：Locate 找条可读 Capture 提供的「全屏/主屏一帧」作为输入图；Capture 可依赖公共 `Roi` 类型（不因此承担找条职责）。
- **预览窗**：真机 + 模拟器并排的调试 UI 属编排工具，不放在 `autofish` 五段内；见 `src/tools/`。
- 代码：`src/autofish/{locate,capture,detect,decide,act}/`；总线 `src/common/pubsub/`。

失败（总览）：任一段失败不得由其他段「顺手修补」职责；应回到该段或清空 ROI / 停止执行。

## 解决步骤

1. 五段分工与子文档架子（已完成；目录由 `vision` 更名为 `autofish`）。
2. 订阅串接 → [`docs/autofish/pipeline/`](pipeline/)。
3. 按子文档顺序补齐各段契约并实现（进行中；子页待拆处先对话确认再写）。
