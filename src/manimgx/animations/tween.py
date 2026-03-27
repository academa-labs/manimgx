from typing import TYPE_CHECKING, Any

import numpy as np

from manimgx.animations.bases.animation import Animation
from manimgx.primitives.color import parse_color
from manimgx.primitives.rate_functions import RateFunc, smooth
from manimgx.primitives.units import RunTime

if TYPE_CHECKING:
    from manimgx.mobjects.bases.mobject import Mobject
    from manimgx.scene import _Timeline


class Tween(Animation):
    """Tween arbitrary dataclass fields on any target (Mobject or ValueTracker).

    For Mobject targets, the mobject is automatically registered with the
    timeline so it becomes visible.  For non-Mobject targets (e.g.
    ValueTracker), only the interpolation entry is scheduled.
    """

    def __init__(
        self,
        target: Any,
        *,
        run_time: RunTime = 1.0,
        rate_func: RateFunc = smooth,
        **targets: Any,
    ) -> None:
        if not targets:
            msg = "Tween requires at least one target keyword argument"
            raise ValueError(msg)
        self._target = target
        self._targets = targets
        super().__init__(run_time=run_time, rate_func=rate_func)

    def _prepare(self) -> None:
        self._lerps: list[_Lerp] = []
        for name, target in self._targets.items():
            if not hasattr(self._target, name):
                msg = f"{type(self._target).__name__} has no attribute {name!r}"
                raise AttributeError(msg)
            start = getattr(self._target, name)
            self._lerps.append(_make_lerp(name, start, target))

    def _play(self, builder: "_Timeline", run_time: float) -> None:
        self._register_scene_mobjects(builder)
        builder._add_entry(self._interpolate, run_time, self.rate_func)
        self._interpolate(self.rate_func(1.0))

    def _interpolate(self, alpha: float) -> None:
        for lerp in self._lerps:
            setattr(self._target, lerp.name, lerp.at(alpha))

    def _scene_mobjects(self) -> "tuple[Mobject, ...]":
        from manimgx.mobjects.bases.mobject import Mobject

        if isinstance(self._target, Mobject):
            return (self._target,)
        return ()


class _Lerp:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def at(self, alpha: float) -> Any:
        raise NotImplementedError


class _FloatLerp(_Lerp):
    __slots__ = ("_start", "_target")

    def __init__(self, name: str, start: float, target: float) -> None:
        super().__init__(name)
        self._start = start
        self._target = target

    def at(self, alpha: float) -> float:
        return self._start + alpha * (self._target - self._start)


class _ArrayLerp(_Lerp):
    __slots__ = ("_start", "_target")

    def __init__(self, name: str, start: np.ndarray, target: np.ndarray) -> None:
        super().__init__(name)
        self._start = start.copy()
        self._target = target

    def at(self, alpha: float) -> np.ndarray:
        return self._start + alpha * (self._target - self._start)


class _ColorLerp(_Lerp):
    __slots__ = ("_start_rgb", "_target_rgb")

    def __init__(self, name: str, start_color: str, target_color: str) -> None:
        super().__init__(name)
        self._start_rgb = parse_color(start_color)
        self._target_rgb = parse_color(target_color)

    def at(self, alpha: float) -> str:
        sr, sg, sb = self._start_rgb
        tr, tg, tb = self._target_rgb
        r = int(sr + alpha * (tr - sr))
        g = int(sg + alpha * (tg - sg))
        b = int(sb + alpha * (tb - sb))
        return f"#{r:02x}{g:02x}{b:02x}"


def _make_lerp(name: str, start: Any, target: Any) -> _Lerp:
    if isinstance(start, str):
        if not isinstance(target, str):
            msg = f"Field {name!r}: expected str target, got {type(target).__name__}"
            raise TypeError(msg)
        return _ColorLerp(name, start, target)
    if isinstance(start, np.ndarray):
        return _ArrayLerp(name, start, np.asarray(target))
    if isinstance(start, (int, float)):
        return _FloatLerp(name, float(start), float(target))
    msg = f"Field {name!r}: unsupported type {type(start).__name__} for tweening"
    raise TypeError(msg)
