"""可调参数：窗口、张力条安全区、鱼漂手感、进度。"""

from __future__ import annotations

import json

from common.paths import assets_dir

_ASSETS = assets_dir()
_METRICS = json.loads((_ASSETS / "metrics.json").read_text())

# ---- 资源 ----
TENSION_BAR = _ASSETS / "tension_bar.png"
PROGRESS_BAR = _ASSETS / "progress_bar.png"
BOBBER = _ASSETS / "bobber.png"
FISH_MARKER = _ASSETS / "fish_marker.png"

# ---- 张力条几何 ----
TENSION_W = int(_METRICS["tension_w"])
TENSION_H = int(_METRICS["tension_h"])
SAFE_LEFT = int(_METRICS["safe_left"])
SAFE_RIGHT = int(_METRICS["safe_right"])
PROGRESS_W = int(_METRICS["progress_w"])
PROGRESS_H = int(_METRICS["progress_h"])

# ---- 窗口 ----
PAD_X = 48
PAD_Y = 56
GAP = 28
WINDOW_WIDTH = max(TENSION_W, PROGRESS_W) + PAD_X * 2
WINDOW_HEIGHT = PAD_Y * 2 + TENSION_H + GAP + PROGRESS_H + 48
FPS = 60
TITLE = "Albion Fishing"
BG_COLOR = (38, 42, 32)

# ---- 高频点按：按住→向右，松开→向左；长按会撞右红，松太久撞左红 ----
PULL_FORCE_START = 720.0    # 点下瞬间向右力（短按够用）
PULL_FORCE_RAMP = 3200.0    # 每多按 1 秒额外向右力（约 0.3s 后开始危险）
PULL_FORCE_CAP = 1800.0     # 向右力硬上限
FISH_ACCEL_BASE = 620.0     # 松开后向左基础
FISH_ACCEL_VARIATION = 260.0
FISH_VARIATION_HZ = 0.85
VELOCITY_DRAG = 2.2         # 阻尼：削弱滑行惯性
RELEASE_RIGHT_BRAKE = 14.0  # 松开时额外刹掉向右速度（对齐真机：松即回左）
MAX_SPEED = 360.0
RIGHT_SPEED_SCALE = 0.55    # 向右最大速度更低，抑制右惯性
LEFT_SPEED_SCALE = 1.05
START_X_RATIO = 0.50

PROGRESS_PER_SEC = 0.13
PROGRESS_LOSS_PER_SEC = 0.09
PROGRESS_RATE_AT_LEFT = 0.20
PROGRESS_RATE_AT_RIGHT = 1.90
PROGRESS_START = 0.0
