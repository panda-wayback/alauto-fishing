"""拉鱼策略接口。"""

from __future__ import annotations

from typing import Protocol

from sim.api import Observation


class PullPolicy(Protocol):
    """根据观测决定本帧是否按住。"""

    def decide(self, obs: Observation) -> bool: ...
