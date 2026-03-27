from dataclasses import dataclass

from manimgx.animations.bases.animation_on_mobject import AnimationOnMobject
from manimgx.mobjects.bases.mobject import Mobject
from manimgx.primitives.vector import Vec3


@dataclass
class ScaleInPlace(AnimationOnMobject):
    scale_factor: float

    def _prepare(self) -> None:
        self._pivot = self.mobject.center.copy()
        self._starts: list[tuple[Mobject, Vec3, Vec3]] = [
            (sub, sub.position.copy(), sub.scale_vec.copy())
            for sub in self.mobject.iter_submobjects
        ]

    def _interpolate(self, alpha: float) -> None:
        factor = 1.0 + (self.scale_factor - 1.0) * alpha
        for sub, start_pos, start_scale in self._starts:
            sub.scale_vec = start_scale * factor
            sub.position = self._pivot + factor * (start_pos - self._pivot)
