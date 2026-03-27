from dataclasses import dataclass

from manimgx.animations.bases.animation_on_mobject import AnimationOnMobject
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject


@dataclass
class Create(AnimationOnMobject[PlanarPathMobject]):
    def _interpolate(self, alpha: float) -> None:
        pass  # TODO: implement using set_partial / reset_partial
