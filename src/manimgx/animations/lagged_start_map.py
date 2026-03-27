from typing import Any

from manimgx.animations.bases.animation_group import LaggedStart
from manimgx.animations.bases.animation_on_mobject import AnimationOnMobject
from manimgx.mobjects.bases.mobject import Mobject
from manimgx.primitives.rate_functions import RateFunc, linear
from manimgx.primitives.units import RunTime


class LaggedStartMap(LaggedStart):
    def __init__(
        self,
        animation_class: type[AnimationOnMobject[Any]],
        mobject: Mobject,
        *,
        run_time: RunTime = 2.0,
        rate_func: RateFunc = linear,
        **kw: Any,
    ) -> None:
        animations = [
            animation_class(mobject=child, rate_func=rate_func)
            for child in mobject.direct_submobjects
        ]
        super().__init__(*animations, run_time=run_time, **kw)
