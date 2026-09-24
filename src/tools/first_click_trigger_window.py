"""兼容旧导入路径：请改用 sound_panel / backtest_panel。"""

from tools.backtest_panel import AudioBacktestPanel
from tools.sound_panel import FirstClickTriggerPanel

__all__ = ["AudioBacktestPanel", "FirstClickTriggerPanel"]
