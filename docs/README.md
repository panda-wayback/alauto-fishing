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
| └ 声音开钓 / 会话 | [`docs/autofish/first_click_trigger/`](autofish/first_click_trigger/) | 可选听声点第一下；与自动拉漂独立 |
| └ 调试壳界面 | [`docs/autofish/shell/`](autofish/shell/) | 主控打勾；标定/声音/更多分页面 |
| **通用库** | [`docs/common/`](common/) | 无业务基础设施 |
| └ 订阅总线 | [`docs/common/pubsub/`](common/pubsub/) | 进程内 Pub/Sub |
| └ 运行权限 | [`docs/common/permissions/`](common/permissions/) | 截屏/控鼠/音频授权引导 |

调试预览窗在代码 `src/tools/`，不属于上表业务段；壳布局以「权限(可收起) → 画面工作台(MONITOR+读数+BAR) → 设置(策略/操作/声音触发) → 底栏日志」为准，见 [`docs/autofish/`](autofish)。

推进：五段流水线、声音开钓、调试壳已落地；此后按各能力页改契约 → 再改代码。
