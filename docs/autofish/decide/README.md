# 算法判定（Decide）

## 目标

只根据识别结果判定下一步操作意图（按住 / 松开）。本段不截屏、不识图、不点鼠标。

## 要实现的

- 身份：**策略订阅者**。订阅识别段 `Pos`（及钓鱼状态）；发布 **动作意图**。
- 规则（与 [`docs/simulator/algo-test/`](../../simulator/algo-test/) 同型，**阈值可配置**）：
  - pos **&lt; low** → 意图为按住（默认 low=50）
  - pos **&gt; high** → 意图为松开（默认 high=80；亦可 90）
  - low～high → 保持当前意图
- 切换约束：按住↔松开两次切换至少间隔 **0.2s**，再加 `U(0, 0.1)` s；未到间隔不改意图。
- 无有效 Pos / 非钓鱼态 → 意图为松开（安全）。
- 阈值由调试壳/配置注入；Decide **不**自行改阈值。
- 不做：mss、CV、键鼠落点。

## 解决步骤

1. 约定主题名 `ActionIntent`（载荷：要按住 / 要松开 + 时间戳 + 可选原因）。
2. DecideWorker 订 `Pos`（+ `FishingState`）→ 阈值策略 → 发 `ActionIntent`。
3. 与模拟器侧 `ThresholdHoldPolicy` 规则对齐；真机 Pos 直接当绿区 0～100 使用。
