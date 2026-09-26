# 真机自动拉鱼（功能架构）

## 目标

真机自动拉鱼的**功能架构**：按五段拆开，每段只做一件事；段与段经总线交接。与 [`docs/simulator/`](../simulator/) 模拟器分离。不含 YOLO。

可选：**声音开钓（A）** 与 **自动拉漂（B）** 独立开关，支持全自动 / 只拉漂 / 全手钓。

## 要实现的

| 段 | 只做什么 | 产出 | 子文档 |
|---|---|---|---|
| **1. 圈定范围** | 手框产出**天花板 ROI**并存储；同步为 mss 初始截图范围 | 天花板 ROI / 无 ROI | [`docs/autofish/locate/`](locate/) |
| **2. 截图** | mss **只**按**当前 ROI**持续截帧；无 ROI 则不截 | 最新 Frame | [`docs/autofish/capture/`](capture/) |
| **3. 识别** | 订 ROI+Frame：在手框画面内绿+5% 找白得 0～100；**不改 mss** | Pos | [`docs/autofish/detect/`](detect/) |
| **4. 算法** | 订 Pos，阈值策略产出按住/松开意图 | ActionIntent | [`docs/autofish/decide/`](decide/) |
| **5. 执行** | 订意图，系统级鼠标按下/松开（当前光标） | 键态变化 | [`docs/autofish/act/`](act/) |
| **（可选）声音开钓 A** | 会话状态机：听声 → 点第一下 → 等漂 → 交 B | 开钓第一下 / 会话态 | [`docs/autofish/first_click_trigger/`](first_click_trigger/) |
| **调试壳** | 主控只打勾；标定/声音/更多分页面 | — | [`docs/autofish/shell/`](shell/) |
| **打包过期** | 构建填天数；到期打开退出并尽删安装目录 | — | [`docs/autofish/expire/`](expire/) |
| **密钥激活** | 输入密钥；按天数授权（与打包过期独立） | — | [`docs/autofish/license/`](license/) |

### 能力组合（A / B）

| 模式 | A 声音开钓 | B 自动拉漂 | 谁点第一下 | 谁拉漂 |
|---|---|---|---|---|
| 全自动 | 开 | 开 | 程序（水声） | 程序（Pos） |
| 只拉漂 | 关 | 开 | 用户 | 程序（Pos） |
| 全手钓 | 关 | 关 | 用户 | 用户 |

约束：

- 主线：手框存盘 → mss=手框 → 截帧 → 识别 Pos；Detect 不改 mss。  
- 段不越权；串接见 [`docs/autofish/pipeline/`](pipeline/)。  
- A 独立会话机；仅 `WAIT` 听声；细则见 [`docs/autofish/first_click_trigger/`](first_click_trigger/)。  
- **壳 UI**：主控仅「自动拉漂(B) / 声音开钓(A)」勾选 + 精简状态 + 日志；无监控开关（有 ROI 则常开 Capture/Detect）；其余进标定/声音/更多页面。见 [`docs/autofish/shell/`](shell/)。  
- 代码：`src/autofish/...`、`src/tools/`；总线 `src/common/pubsub/`。

失败：段失败不互相顶替职责；A 回 `WAIT` 不拖垮 Capture/Detect。

## 解决步骤

1. 五段与 pipeline / Decide / Act（已完成）。  
2. 声音开钓能力与会话状态机（已完成）→ [`first_click_trigger/`](first_click_trigger/)。  
3. 壳 UI（主控 A/B + 分页面）（已完成）→ [`shell/`](shell/)。  
4. 打包过期自毁 → [`expire/`](expire/)。  
5. 密钥激活（离线半套）→ [`license/`](license/)。
