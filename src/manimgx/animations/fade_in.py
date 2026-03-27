from dataclasses import dataclass

from manimgx.animations.bases.animation_on_mobject import AnimationOnMobject
from manimgx.mobjects.bases.fill_stroke_mobject import FillStrokeMobject
from manimgx.mobjects.bases.mobject import Mobject


@dataclass
class _FadeBase(AnimationOnMobject):
    def _prepare(self) -> None:
        self._snapshots: list[tuple[Mobject, str, float]] = []
        for sub in self.mobject.iter_submobjects:
            if isinstance(sub, FillStrokeMobject):
                self._snapshots.append((sub, "fill_opacity", sub.fill_opacity))
                self._snapshots.append((sub, "stroke_opacity", sub.stroke_opacity))
            else:
                self._snapshots.append((sub, "opacity", sub.opacity))

    def _opacity_factor(self, alpha: float) -> float:
        raise NotImplementedError

    def _interpolate(self, alpha: float) -> None:
        factor = self._opacity_factor(alpha)
        for sub, field, start_val in self._snapshots:
            setattr(sub, field, start_val * factor)


@dataclass
class FadeIn(_FadeBase):
    def _opacity_factor(self, alpha: float) -> float:
        return alpha
