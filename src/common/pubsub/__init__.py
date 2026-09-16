"""进程内订阅总线：通用 EventBus。方案见 docs/common/pubsub/。"""

from common.pubsub.bus import EventBus, Subscriber

__all__ = ["EventBus", "Subscriber"]
