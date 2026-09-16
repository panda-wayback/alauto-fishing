# 真机流水线串接（订阅式）

## 目标

把五段（圈定 → 截图 → 识别 → 算法 → 执行）用统一总线串起来：每段只发布/订阅自己的主题，不互相调用内部实现。总线契约见 [`docs/common/pubsub/`](../../common/pubsub/)。

## 要实现的

### 段与主题

| 段 | 文档 | 发布 | 订阅 / 读取 |
|---|---|---|---|
| 1 圈定范围 | [`docs/autofish/locate/`](../locate/) | ROI（点1、点2） | （可选）钓鱼状态以决定重找 |
| 2 截图 | [`docs/autofish/capture/`](../capture/) | Frame | 当前 ROI；**无 ROI 则不出帧** |
| 3 识别 | [`docs/autofish/detect/`](../detect/) | Pos | 最新 Frame |
| （辅助）钓鱼状态 | 本页约定 | FishingState | ROI + Pos |
| 4 算法 | [`docs/autofish/decide/`](../decide/) | **ActionIntent** | Pos + FishingState |
| 5 执行 | [`docs/autofish/act/`](../act/) | （可选回执，非必须） | ActionIntent |

主题至少：`ROI`、`Frame`、`Pos`、`FishingState`、`ActionIntent`。

### 版本与作废

- ROI 变更递增版本；旧 Frame 作废。
- Frame / Pos 带 `roi_version`；与当前不一致则丢弃。

### 钓鱼状态

- `IDLE` / `FISHING` / `LOST`（条与读数是否可用）；供算法与执行做安全判断。

### 约束

- 禁止跨段直调业务逻辑（如算法里调 mss；Decide 里点鼠标；**禁止 Act/壳写模拟器 holding**）。
- 允许：Locate 使用 Capture 的主屏一帧；各段共用 `Roi` 类型；Decide 复用阈值规则（自洽实现）。
- 推送 + 快照均可；高频 Frame latest-wins。
- **调试壳**（`src/tools/`）只订阅展示 + **独立启停**：
  - **监控**（Capture+Detect，可含 Locate）
  - **策略**（Decide）
  - **操作**（Act，**默认关**；勾选才 `start`，真鼠标）
  - 模拟器属 [`docs/simulator/`](../../simulator/)，与壳零状态耦合；可同屏练习，但不得被 Act 同步改内部状态。
- 监控显示原画面见 [`docs/autofish/`](../) 约束；叠层仅标鱼漂命中。
- 调试壳：ROI **手框**（=监控范围=CV 范围；重框兜底）；无「找绿」入口。
- 本轮不换 PySide6；壳仍可用现有 UI，职责以上述开关为准。

## 解决步骤

1. 五段映射与主题表写入本页（已完成）。
2. 通用总线 → [`docs/common/pubsub/`](../../common/pubsub/)（已完成）。
3. Decide / Act 与 `ActionIntent`（已完成）。
4. 壳：三独立开关 + 断模拟器耦合 + 读数提频（已完成）。
