"""拉鱼策略接口。"""

from __future__ import annotations

from typing import Protocol

from sim.api import Observation


class PullPolicy(Protocol):
    """根据观测决定本帧是否按住；有局内状态的策略另实现 reset()，每局开始前被调用。"""

    def decide(self, obs: Observation) -> bool: ...
