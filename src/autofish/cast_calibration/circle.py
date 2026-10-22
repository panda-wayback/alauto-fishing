"""抛杆标定：3D 透视投影形成的上窄下宽贴地环。

标定数据与屏幕分辨率无关，只存：
- cx / cy：人物圆心相对屏幕宽 / 高的比例；
- radius_ratio：基准半径相对屏幕短边的比例；
- angle_deg：俯视角度。

参考环通过透视公式逐点采样成轮廓点列绘制，不是普通椭圆，也不使用
fitEllipse；世界同心正圆投影后上密下疏、近大远小。

后续若从真实游戏画面识别该环，应使用二值化轮廓提取（Contours）+
透视变换拉 Bird's Eye View，不做椭圆拟合。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from common.paths import data_root

DEFAULT_CAST_CIRCLE_PATH = data_root() / "cast_circle.json"
DEFAULT_RADIUS_RATIO = 0.35


@dataclass(frozen=True)
class CastCircle:
    """分辨率无关的标定值；比例均以 1.0 为满尺寸。"""

    cx: float
    cy: float
    angle_deg: float
    radius_ratio: float = DEFAULT_RADIUS_RATIO

    def __post_init__(self) -> None:
        if not 0.0 < self.angle_deg <= 90.0:
            raise ValueError("angle_deg must be in (0, 90]")
        if self.radius_ratio <= 0:
            raise ValueError("radius_ratio must be positive")

    @classmethod
    def from_pixels(
        cls,
        px: float,
        py: float,
        radius_px: float,
        screen_w: int,
        screen_h: int,
        angle_deg: float,
    ) -> "CastCircle":
        if screen_w <= 0 or screen_h <= 0:
            raise ValueError("screen size must be positive")
        return cls(
            cx=px / screen_w,
            cy=py / screen_h,
            angle_deg=angle_deg,
            radius_ratio=radius_px / min(screen_w, screen_h),
        )

    def anchor(self, screen_w: int, screen_h: int) -> tuple[float, float]:
        """人物圆心在指定屏幕上的逻辑点。"""
        self._check_screen(screen_w, screen_h)
        return self.cx * screen_w, self.cy * screen_h

    def radius_for(self, screen_w: int, screen_h: int) -> float:
        """基准半径在指定屏幕上的逻辑点。"""
        self._check_screen(screen_w, screen_h)
        return self.radius_ratio * min(screen_w, screen_h)

    @staticmethod
    def _check_screen(screen_w: int, screen_h: int) -> None:
        if screen_w <= 0 or screen_h <= 0:
            raise ValueError("screen size must be positive")

    @property
    def angle_rad(self) -> float:
        return math.radians(self.angle_deg)

    @property
    def vertical_scale(self) -> float:
        return math.sin(self.angle_rad)

    @property
    def perspective(self) -> float:
        """角度越平视，近大远小越强；90° 顶视为 0。"""
        return 0.60 * math.cos(self.angle_rad)

    def with_angle(self, angle_deg: float) -> "CastCircle":
        return CastCircle(self.cx, self.cy, angle_deg, self.radius_ratio)

    def with_anchor_ratio(self, cx: float, cy: float) -> "CastCircle":
        return CastCircle(cx, cy, self.angle_deg, self.radius_ratio)

    def with_radius_ratio(self, radius_ratio: float) -> "CastCircle":
        return CastCircle(self.cx, self.cy, self.angle_deg, radius_ratio)

    def project(
        self, rho: float, phi: float, screen_w: int, screen_h: int
    ) -> tuple[float, float]:
        """世界圆上的 (比例 rho, 方位 phi) 投影为指定屏幕坐标。"""
        ax, ay = self.anchor(screen_w, screen_h)
        radius = self.radius_for(screen_w, screen_h)
        c = self.vertical_scale
        k = self.perspective
        denom = 1.0 - k * rho * math.sin(phi)
        sx = radius * rho * math.cos(phi) / denom
        sy = radius * c * rho * math.sin(phi) / denom
        return ax + sx, ay + sy

    def reference_polygon(
        self,
        rho: float,
        screen_w: int,
        screen_h: int,
        segments: int = 128,
    ) -> list[tuple[float, float]]:
        return [
            self.project(rho, 2.0 * math.pi * i / segments, screen_w, screen_h)
            for i in range(segments)
        ]

    def normalized_radius(
        self, x: float, y: float, screen_w: int, screen_h: int
    ) -> float:
        """由屏幕鼠标点反推世界半径比例；人物点 0、外环 1、环外 >1。"""
        ax, ay = self.anchor(screen_w, screen_h)
        radius = self.radius_for(screen_w, screen_h)
        sx = (float(x) - ax) / radius
        sy = (float(y) - ay) / (radius * self.vertical_scale)
        k = self.perspective
        denom = 1.0 + k * sy
        if denom <= 1e-9:
            return math.inf
        return math.sqrt(sx * sx + sy * sy) / denom

    def target_power_ratio(
        self, x: float, y: float, screen_w: int, screen_h: int
    ) -> float:
        """鼠标点对应的抛杆目标力度比例，夹到 [0, 1]。

        鼠标在人物点为 0；在参考圈上为 1；圈外（含反推发散）一律 1（满力）。
        """
        rho = self.normalized_radius(x, y, screen_w, screen_h)
        if not math.isfinite(rho):
            return 1.0
        return max(0.0, min(1.0, rho))


def save_cast_circle(circle: CastCircle, path: Path | None = None) -> Path:
    p = path or DEFAULT_CAST_CIRCLE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cx": float(circle.cx),
        "cy": float(circle.cy),
        "angle_deg": float(circle.angle_deg),
        "radius_ratio": float(circle.radius_ratio),
    }
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def load_cast_circle(path: Path | None = None) -> CastCircle:
    p = path or DEFAULT_CAST_CIRCLE_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return CastCircle(
        cx=float(data["cx"]),
        cy=float(data["cy"]),
        angle_deg=float(data["angle_deg"]),
        radius_ratio=float(data.get("radius_ratio", DEFAULT_RADIUS_RATIO)),
    )
