from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from manimgx.animations.bases.animation import Animation
from manimgx.mobjects.bases.mobject import Mobject

if TYPE_CHECKING:
    from manimgx.scene import _Timeline


@dataclass
class AnimationOnMobject[M: Mobject](Animation):
    mobject: M

    def _scene_mobjects(self) -> tuple[Mobject, ...]:
        return (self.mobject,)

    def _play(self, builder: "_Timeline", run_time: float) -> None:
        self._register_scene_mobjects(builder)
        builder._add_entry(self._interpolate, run_time, self.rate_func)
        self._interpolate(self.rate_func(1.0))

    @abstractmethod
    def _interpolate(self, alpha: float) -> None: ...
