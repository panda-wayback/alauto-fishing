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
| └ 运行权限 | [`docs/common/permissions/`](common/permissions/) | 截屏/控鼠授权引导 |

调试预览窗在代码 `src/tools/`，不属于上表业务段；左监控 + 右条界标记；监控显示原画面（可叠框/线）见 [`docs/autofish/`](autofish/) 约束。

推进顺序：Decide/Act 契约已写入 → 实现订阅链与预览（真鼠标 + 日志）→ common 按页校对。
