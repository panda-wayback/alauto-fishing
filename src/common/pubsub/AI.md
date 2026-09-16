# src/common/pubsub/ 功能说明

更新时间：2026-09-17

## 本文件夹职责

进程内通用发布/订阅核心。方案见 `docs/common/pubsub/`。

## 目录清单

- `bus.py` — `EventBus`（subscribe / unsubscribe / publish）

## 对外契约

- `EventBus.subscribe(topic, callback)` — 订阅；同回调不重复叠加
- `EventBus.unsubscribe(topic, callback)` — 退订
- `EventBus.publish(topic, event)` — 发布；单订阅者异常不影响其他
- `EventBus.subscriber_count(topic)` — 调试用订阅数

## 约束

- 禁止依赖 `autofish` / `sim` / `algo` / UI。
- 禁止在本包定义业务主题或快照；域主题由使用方（如 `autofish.topics`）提供。
