from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(kw_only=True, eq=False)
class ValueTracker:
    """A non-visible animatable float holder.

    Other Mobjects read the value via updaters::

        tracker = ValueTracker(value=0)
        circle.add_updater(lambda m, t: m.shift_to_x(tracker.value))
        self.play(Tween(tracker, value=5.0))

    ValueTracker is intentionally *not* a Mobject.  It carries no geometry,
    no position, no material -- only a scalar ``value`` that can be tweened
    and read by updaters on real Mobjects.

    Register it with ``scene.add(tracker)`` so its own updaters (if any) are
    called each frame.
    """

    value: float = 0.0
    _updaters: "list[Callable[[ValueTracker, float], None]]" = field(
        default_factory=list, init=False, repr=False
    )

    def add_updater(
        self, func: "Callable[[ValueTracker, float], None]"
    ) -> "ValueTracker":
        self._updaters.append(func)
        return self

    def remove_updater(
        self, func: "Callable[[ValueTracker, float], None]"
    ) -> "ValueTracker":
        self._updaters = [u for u in self._updaters if u is not func]
        return self

    def clear_updaters(self) -> "ValueTracker":
        self._updaters.clear()
        return self

    @property
    def updaters(self) -> "list[Callable[[ValueTracker, float], None]]":
        return list(self._updaters)
