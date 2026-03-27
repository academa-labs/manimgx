from dataclasses import dataclass, field

from manimgx.animations.bases.animation_on_mobject import AnimationOnMobject
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject
from manimgx.primitives.rate_functions import RateFunc, smooth
from manimgx.primitives.units import RunTime


@dataclass
class Write(AnimationOnMobject[PlanarPathMobject]):
    fill_lag: float = field(default=0.5, kw_only=True)
    rate_func: RateFunc = field(default=smooth, kw_only=True)
    run_time: RunTime = field(default=2.0, kw_only=True)

    def _interpolate(self, alpha: float) -> None:
        pass  # TODO: implement using set_partial / reset_partial
