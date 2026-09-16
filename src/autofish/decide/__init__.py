"""段4：算法判定。"""

from autofish.decide.policy import ThresholdPosPolicy

__all__ = ["DecideWorker", "ThresholdPosPolicy"]


def __getattr__(name: str):
    if name == "DecideWorker":
        from autofish.decide.worker import DecideWorker

        return DecideWorker
    raise AttributeError(name)
