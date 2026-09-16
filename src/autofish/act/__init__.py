"""段5：执行操作。"""

from autofish.act.mouse import MouseActuator

__all__ = ["ActWorker", "MouseActuator"]


def __getattr__(name: str):
    if name == "ActWorker":
        from autofish.act.worker import ActWorker

        return ActWorker
    raise AttributeError(name)
