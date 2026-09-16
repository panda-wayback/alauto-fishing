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
| 4 算法 | [`docs/autofish/decide/`](../decide/) | 动作意图 | Pos + FishingState |
| 5 执行 | [`docs/autofish/act/`](../act/) | （无，或执行回执待拆） | 动作意图 |

主题至少：`ROI`、`Frame`、`Pos`、`FishingState`；动作意图主题在 decide/act 待拆时补名。

### 版本与作废

- ROI 变更递增版本；旧 Frame 作废。
- Frame / Pos 带 `roi_version`；与当前不一致则丢弃。

### 钓鱼状态

- `IDLE` / `FISHING` / `LOST`（条与读数是否可用）；供算法与执行做安全判断。

### 约束

- 禁止跨段直调业务逻辑（如算法里调 mss）。
- 允许：Locate 使用 Capture 的主屏一帧；各段共用 `Roi` 类型。
- 推送 + 快照均可；高频 Frame latest-wins。
- 真机/模拟器并排预览属 `src/tools/`，不是五段之一。

## 解决步骤

1. 五段映射与主题表写入本页（已完成）。
2. 通用总线 → [`docs/common/pubsub/`](../../common/pubsub/)（已完成）。
3. 按各段子文档补齐后，校对实现与订阅关系（待各段待拆完成）。
