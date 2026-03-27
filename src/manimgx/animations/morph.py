from dataclasses import dataclass, field

from manimgx.animations.bases.animation_on_mobject import AnimationOnMobject
from manimgx.mobjects.bases.mobject import Mobject


@dataclass
class Morph(AnimationOnMobject):
    target: Mobject = field(kw_only=True)

    def _prepare(self) -> None:
        pass  # TODO: reimplement without engine-level morph

    def _interpolate(self, alpha: float) -> None:
        pass  # TODO: reimplement without engine-level morph
