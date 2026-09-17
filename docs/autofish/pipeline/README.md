# 真机流水线串接（订阅式）

## 目标

把五段（圈定 → 截图 → 识别 → 算法 → 执行）用统一总线串起来：每段只发布/订阅自己的主题，不互相调用内部实现。总线契约见 [`docs/common/pubsub/`](../../common/pubsub/)。

## 要实现的

### 段与主题

| 段 | 文档 | 发布 | 订阅 / 读取 |
|---|---|---|---|
| 1 圈定范围 | [`docs/autofish/locate/`](../locate/) | 天花板 ROI（兼初始当前）；存盘 | （可选）钓鱼状态 |
| 2 截图 | [`docs/autofish/capture/`](../capture/) | Frame | **当前 ROI**；无则不出帧 |
| 3 识别 | [`docs/autofish/detect/`](../detect/) | Pos | ROI + 最新 Frame；**不发布 ROI** |
| （辅助）钓鱼状态 | 本页约定 | FishingState | ROI + Pos |
| 4 算法 | [`docs/autofish/decide/`](../decide/) | **ActionIntent** | Pos + FishingState |
| 5 执行 | [`docs/autofish/act/`](../act/) | （可选回执） | ActionIntent |

主题至少：`ROI`、`Frame`、`Pos`、`FishingState`、`ActionIntent`。

### ROI 双层

- **天花板 / 当前**：手框存盘后两者相同；Detect **不得**改写当前 ROI。
- 清空手框则两者皆空。

### 版本与作废

- 当前 ROI 变更递增版本；旧 Frame 作废。
- Frame / Pos 带 `roi_version`；与当前不一致则丢弃。

### 钓鱼状态

- `IDLE` / `FISHING` / `LOST`；供算法与执行做安全判断。

### 约束

- 禁止跨段直调业务逻辑。
- 允许：Locate 用主屏一帧；共用 `Roi`。
- 推送 + 快照均可；高频 Frame latest-wins。
- **调试壳（PySide6）**：订 **Frame（监控画面）** + **Pos（读数）**；ROI **手框**同步 mss；三独立勾选；**策略与操作默认开**；模拟器嵌窗手玩、零耦合；**无快捷键**；截屏直接抓主屏。

## 解决步骤

1. 五段映射与主题表写入本页（已完成）。
2. 通用总线 → [`docs/common/pubsub/`](../../common/pubsub/)（已完成）。
3. Decide / Act 与 `ActionIntent`（已完成）。
4. 壳：三独立开关 + 断模拟器耦合（已完成）。
5. mss 仅随手框；Detect 不改 ROI（已完成）。
6. 调试壳 PySide6 重做（已完成）。
