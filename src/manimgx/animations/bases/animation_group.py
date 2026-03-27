from typing import TYPE_CHECKING, Any

from manimgx.animations.bases.animation import Animation
from manimgx.primitives.rate_functions import RateFunc, linear
from manimgx.primitives.units import RunTime

if TYPE_CHECKING:
    from manimgx.scene import _Timeline


class AnimationGroup(Animation):
    def __init__(
        self,
        *animations: Animation,
        lag_ratio: float = 0.0,
        run_time: RunTime = 1.0,
        rate_func: RateFunc = linear,
    ):
        self.animations = list(animations)
        self.lag_ratio = lag_ratio
        super().__init__(run_time=run_time, rate_func=rate_func)

    def _play(self, builder: "_Timeline", run_time: float) -> None:
        if not self.animations:
            return
        sub = builder._create_sub_timeline(run_time, self.rate_func)
        n = len(self.animations)
        total_slots = 1.0 + (n - 1) * self.lag_ratio
        child_dur = run_time / total_slots
        step = self.lag_ratio * child_dur

        if self.lag_ratio < 1.0:
            for anim in self.animations:
                anim._prepare()
            for i, anim in enumerate(self.animations):
                sub._cursor = i * step
                sub._play_prepared(anim, run_time=child_dur)
        else:
            for i, anim in enumerate(self.animations):
                sub._cursor = i * step
                sub.play(anim, run_time=child_dur)


class Succession(AnimationGroup):
    def __init__(self, *animations: Animation, lag_ratio: float = 1.0, **kw: Any):
        super().__init__(*animations, lag_ratio=lag_ratio, **kw)


class LaggedStart(AnimationGroup):
    def __init__(self, *animations: Animation, lag_ratio: float = 0.05, **kw: Any):
        super().__init__(*animations, lag_ratio=lag_ratio, **kw)
