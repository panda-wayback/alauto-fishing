# albn-fishing 方案索引

## 目标

本页只做文档入口：模拟器与真机自动拉鱼分开；通用库单独成块。

## 解决步骤

| 块 | 路径 | 是什么 |
|---|---|---|
| **模拟器** | [`docs/simulator/`](simulator/) | 桌面拉鱼小游戏，供人玩与测算法 |
| └ 难度 | [`docs/simulator/difficulty/`](simulator/difficulty/) | T1–T8 |
| └ 算法测试分包 | [`docs/simulator/algo-test/`](simulator/algo-test/) | `sim` / `algo` 无头契约 |
| **真机自动拉鱼** | [`docs/autofish/`](autofish/) | 功能架构：圈定→截图→识别→算法→执行 |
| └ 订阅串接 | [`docs/autofish/pipeline/`](autofish/pipeline/) | 五段如何经总线交接 |
| **通用库** | [`docs/common/`](common/) | 无业务基础设施 |
| └ 订阅总线 | [`docs/common/pubsub/`](common/pubsub/) | 进程内 Pub/Sub |

调试预览窗（真机+模拟器并排）在代码 `src/tools/`，不属于上表业务段。

推进顺序：先模拟器与算法测试 → 再 autofish 各段待拆 → common 按页校对实现。
