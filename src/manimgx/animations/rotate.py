from dataclasses import dataclass, field

import numpy as np

from manimgx.animations.bases.animation_on_mobject import AnimationOnMobject
from manimgx.mobjects.bases.mobject import Mobject
from manimgx.primitives.quaternion import (
    quat_from_angle_axis,
    quat_multiply,
    quat_rotate_vectors,
)
from manimgx.primitives.units import PI
from manimgx.primitives.vector import Vec3, Vec4


@dataclass
class Rotate(AnimationOnMobject):
    angle: float = PI
    axis: tuple[float, float, float] = field(default=(0.0, 0.0, 1.0), kw_only=True)

    def _prepare(self) -> None:
        self._pivot = self.mobject.center.copy()
        self._axis = np.asarray(self.axis)
        self._starts: list[tuple[Mobject, Vec3, Vec4]] = [
            (sub, sub.position.copy(), sub.quaternion.copy())
            for sub in self.mobject.iter_submobjects
        ]

    def _interpolate(self, alpha: float) -> None:
        q = quat_from_angle_axis(self.angle * alpha, self._axis)
        for sub, start_pos, start_quat in self._starts:
            offset = (start_pos - self._pivot).reshape(1, 3)
            sub.position = self._pivot + quat_rotate_vectors(q, offset).reshape(3)
            sub.quaternion = quat_multiply(q, start_quat)
