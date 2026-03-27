from dataclasses import dataclass

from manimgx.mobjects.circle import Circle
from manimgx.primitives.color import Opacity, StrokeWidth


@dataclass(kw_only=True, eq=False)
class Dot(Circle):
    radius: float = 0.08
    color: str = "white"
    fill_opacity: Opacity = 1.0
    stroke_width: StrokeWidth = 0.0
