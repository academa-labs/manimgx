import pathlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from manimgx.engine import Camera, Renderer
from manimgx.mobjects.bases.mobject import Mobject
from manimgx.mobjects.value_tracker import ValueTracker
from manimgx.primitives.color import parse_color
from manimgx.primitives.rate_functions import RateFunc, linear
from manimgx.primitives.units import RunTime

if TYPE_CHECKING:
    from manimgx.animations.bases.animation import Animation

type Addable = Mobject | ValueTracker


class Scene(ABC):
    __slots__ = ("_timeline", "camera", "fps", "height", "width")

    def __init__(
        self,
        *,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
    ) -> None:
        self.camera = Camera(background=parse_color("black"))
        self._timeline = _Timeline()
        self.width = max(1, width)
        self.height = max(1, height)
        self.fps = max(1, fps)

    @abstractmethod
    def construct(self) -> None: ...

    def add(self, *objects: Addable) -> None:
        for obj in objects:
            if isinstance(obj, ValueTracker):
                self._timeline._register_value_tracker(obj)
            else:
                self._timeline._register(obj)

    def remove(self, *objects: Addable) -> None:
        for obj in objects:
            if isinstance(obj, ValueTracker):
                self._timeline._unregister_value_tracker(obj)
            else:
                self._timeline._unregister(obj)

    def play(self, *animations: "Animation") -> None:
        self._timeline.play_simultaneous(*animations)

    def wait(self, run_time: RunTime = 1.0) -> None:
        self._timeline._cursor += max(0.0, run_time)

    def render(
        self,
        *,
        output: pathlib.Path | str = "output.mp4",
    ) -> None:
        output = pathlib.Path(output)

        self._timeline = _Timeline()
        renderer = Renderer()

        self.construct()

        finalized = self._timeline._finalize()

        for mob in finalized.mobjects:
            for surface in mob._direct_mesh_instances:
                surface.active = False
            renderer.add(mob._object3d)

        all_mobjects = finalized.mobjects
        all_value_trackers = finalized.value_trackers

        def evaluate_frame(time: float) -> None:
            finalized.evaluate(time)
            for mob in all_mobjects:
                for updater in mob._updaters:
                    updater(mob, time)
            for vt in all_value_trackers:
                for updater in vt._updaters:
                    updater(vt, time)
            for mob in all_mobjects:
                mob._sync_with_engine()

        renderer.set_camera(self.camera)
        renderer.render(
            evaluate_frame=evaluate_frame,
            total_duration=finalized.duration,
            output=output,
            width=self.width,
            height=self.height,
            fps=self.fps,
            supersample=2 if output.suffix in {".png", ".jpg"} else 1,
        )


def _set_visible(mobject: Mobject, *, active: bool) -> None:
    for mi in mobject.iter_mesh_instances:
        mi.active = active


class _Entry:
    __slots__ = ("done", "duration", "evaluate", "rate_func", "start")

    def __init__(
        self,
        start: float,
        duration: float,
        evaluate: Callable[[float], None],
        rate_func: RateFunc,
    ) -> None:
        self.start = start
        self.duration = duration
        self.evaluate = evaluate
        self.rate_func = rate_func
        self.done = False

    def call(self, raw: float) -> None:
        self.evaluate(self.rate_func(raw))


class _FinalizedTimeline:
    """Immutable, sorted timeline ready for monotonic frame-by-frame evaluation.

    Produced by ``_Timeline._finalize()``.  Contains only the data needed
    for the render loop: sorted entries, total duration, and the set of
    mobjects/value-trackers whose mesh instances must be submitted to the GPU.

    Builder-only state (cursor position, registered set, sub-timelines) is
    discarded at finalization time -- it is not needed during rendering and
    keeping it around would muddy the lifecycle.
    """

    __slots__ = ("_entries", "_scan_start", "duration", "mobjects", "value_trackers")

    def __init__(
        self,
        entries: list[_Entry],
        duration: float,
        mobjects: tuple[Mobject, ...],
        value_trackers: tuple[ValueTracker, ...],
    ) -> None:
        self._entries = entries
        self._scan_start = 0
        self.duration = duration
        self.mobjects = mobjects
        self.value_trackers = value_trackers

    def evaluate(self, time: float) -> None:
        """Advance all entries up to *time* (monotonically increasing).

        Entries whose time window has passed are marked done and skipped
        on subsequent calls.  The scan-start pointer advances past
        contiguous completed entries at the front of the list.
        """
        entries = self._entries
        n = len(entries)
        i = self._scan_start
        new_scan_start = i
        while i < n:
            entry = entries[i]
            if entry.start > time:
                break
            if entry.done:
                i += 1
                continue
            if entry.duration <= 0.0:
                entry.call(1.0)
                entry.done = True
                i += 1
                continue
            if time >= entry.start + entry.duration:
                entry.call(1.0)
                entry.done = True
                i += 1
                continue
            entry.call((time - entry.start) / entry.duration)
            i += 1
        while new_scan_start < n and entries[new_scan_start].done:
            new_scan_start += 1
        self._scan_start = new_scan_start

    def _evaluate_nonmonotonic(self, time: float) -> None:
        """Evaluate entries at an arbitrary *time* (may go backwards).

        Used inside non-linear AnimationGroup sub-timelines where the
        rate function can warp time non-monotonically (e.g.
        ``there_and_back``).  Unlike ``evaluate()``, no ``done`` tracking
        or scan-start optimization is applied.
        """
        for entry in self._entries:
            if entry.start > time:
                break
            if entry.duration <= 0.0:
                entry.call(1.0)
                continue
            raw = min(1.0, (time - entry.start) / entry.duration)
            entry.call(raw)


class _Timeline:
    """Builder for recording animation entries during ``Scene.construct()``.

    Spawned by Scene for the top-level timeline, and recursively by
    AnimationGroup for nested time domains with independent rate functions.

    Call ``_finalize()`` after construction to produce a
    ``_FinalizedTimeline`` ready for the render loop.  The builder should
    not be used after finalization.
    """

    __slots__ = (
        "_all_mobjects",
        "_all_value_trackers",
        "_cursor",
        "_entries",
        "_registered",
        "_subs",
        "_value_trackers",
    )

    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._subs: list[tuple[_Timeline, float, float, RateFunc]] = []
        self._registered: dict[Mobject, None] = {}
        self._all_mobjects: dict[Mobject, None] = {}
        self._value_trackers: dict[ValueTracker, None] = {}
        self._all_value_trackers: dict[ValueTracker, None] = {}
        self._cursor: float = 0.0

    def play(self, animation: "Animation", *, run_time: float | None = None) -> None:
        effective = run_time if run_time is not None else animation.run_time
        animation._prepare()
        animation._play(self, effective)
        self._cursor += effective

    def _play_prepared(
        self, animation: "Animation", *, run_time: float | None = None
    ) -> None:
        effective = run_time if run_time is not None else animation.run_time
        animation._play(self, effective)
        self._cursor += effective

    def play_simultaneous(self, *animations: "Animation") -> None:
        for anim in animations:
            anim._prepare()
        start = self._cursor
        max_duration = 0.0
        for anim in animations:
            self._cursor = start
            effective = anim.run_time
            anim._play(self, effective)
            max_duration = max(max_duration, effective)
        self._cursor = start + max_duration

    def _register(self, mobject: Mobject) -> None:
        for sub in mobject.submobjects_iter:
            self._registered[sub] = None
            self._all_mobjects[sub] = None
        self._add_entry(lambda _, _m=mobject: _set_visible(_m, active=True), 0.0)

    def _unregister(self, mobject: Mobject) -> None:
        for sub in mobject.submobjects_iter:
            self._registered.pop(sub, None)
        self._add_entry(lambda _, _m=mobject: _set_visible(_m, active=False), 0.0)

    def _register_value_tracker(self, vt: ValueTracker) -> None:
        self._value_trackers[vt] = None
        self._all_value_trackers[vt] = None

    def _unregister_value_tracker(self, vt: ValueTracker) -> None:
        self._value_trackers.pop(vt, None)

    def _add_entry(
        self,
        evaluate: Callable[[float], None],
        run_time: float,
        rate_func: RateFunc = linear,
    ) -> None:
        self._entries.append(_Entry(self._cursor, run_time, evaluate, rate_func))

    def _create_sub_timeline(self, run_time: float, rate_func: RateFunc) -> "_Timeline":
        sub = _Timeline()
        self._subs.append((sub, self._cursor, run_time, rate_func))
        return sub

    def _finalize(self) -> _FinalizedTimeline:
        """Freeze the timeline: merge sub-timelines, sort entries, return evaluator.

        Returns a ``_FinalizedTimeline`` containing all mobjects that were
        ever registered (not just those currently registered).  Mobjects
        removed via ``scene.remove()`` still need their mesh instances
        submitted to the GPU so that timeline entries (animations,
        visibility toggles) can reference them.
        """
        all_mobjects: dict[Mobject, None] = dict(self._all_mobjects)
        all_vts: dict[ValueTracker, None] = dict(self._all_value_trackers)

        for sub, start, duration, rate_func in self._subs:
            finalized_sub = sub._finalize()
            for m in finalized_sub.mobjects:
                all_mobjects[m] = None
            for vt in finalized_sub.value_trackers:
                all_vts[vt] = None
            if rate_func is linear and finalized_sub.duration > 0.0:
                scale = duration / finalized_sub.duration
                for entry in finalized_sub._entries:
                    self._entries.append(
                        _Entry(
                            start + entry.start * scale,
                            entry.duration * scale,
                            entry.evaluate,
                            entry.rate_func,
                        )
                    )
            else:
                self._entries.append(
                    _Entry(
                        start,
                        duration,
                        lambda raw, _s=finalized_sub: _s._evaluate_nonmonotonic(
                            raw * _s.duration
                        ),
                        rate_func,
                    )
                )

        self._entries.sort(key=lambda e: (e.start, e.duration))
        duration = max(
            self._cursor,
            max((e.start + e.duration for e in self._entries), default=0.0),
        )

        return _FinalizedTimeline(
            entries=self._entries,
            duration=duration,
            mobjects=tuple(all_mobjects),
            value_trackers=tuple(all_vts),
        )
