from abc import abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Self

import numpy as np

from manimgx.engine import Object3D
from manimgx.primitives.vector import ORIGIN, OUT, RIGHT, Vec3, Vec4


@dataclass(kw_only=True, eq=False)
class Mobject:
    position: Vec3 = field(default_factory=lambda: ORIGIN.copy())
    scale_factor: Vec3 = field(default_factory=lambda: np.array([1.0, 1.0, 1.0]))
    quaternion: Vec4 = field(default_factory=lambda: np.array([0.0, 0.0, 0.0, 1.0]))

    _updaters: list[Callable[[Self, float], None]] = field(
        default_factory=list, init=False, repr=False
    )
    _direct_submobjects: list["Mobject"] = field(default_factory=list, init=False)

    @property
    @abstractmethod
    def _object3d(self) -> Object3D: ...

    # Engine sync:
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        handler = getattr(self, f"_on_{name}_changed", None)
        if handler:
            handler(value)

    def _on_position_change(self) -> None:
        self._object3d.position = self.position

    def _on_scale_factor_change(self) -> None:
        self._object3d.scale = self.scale_factor

    def _on_quaternion_change(self) -> None:
        self._object3d.quaternion = self.quaternion

    # Submobjects:

    @property
    def submobjects_iter(self) -> Iterator["Mobject"]:
        stack: list[Mobject] = [self]
        while stack:
            mob = stack.pop()
            yield mob
            stack.extend(reversed(mob._direct_submobjects))

    def add(self, *mobjects: "Mobject") -> Self:
        for m in mobjects:
            if m is self or m in self._direct_submobjects:
                continue
            m._object3d.parent = self._object3d
            self._direct_submobjects.append(m)
        return self

    def remove(self, *mobjects: "Mobject") -> Self:
        to_remove = set(mobjects)
        for m in to_remove:
            if m in self._direct_submobjects:
                m._object3d.parent = None
        self._direct_submobjects = [
            s for s in self._direct_submobjects if s not in to_remove
        ]
        return self

    # Updaters:

    def add_updater(self, func: Callable[[Self, float], None]) -> Self:
        self._updaters.append(func)
        return self

    def remove_updater(self, func: Callable[[Self, float], None]) -> Self:
        self._updaters = [u for u in self._updaters if u is not func]
        return self

    def clear_updaters(self) -> Self:
        self._updaters.clear()
        return self

    # Transforms:

    def shift(self, offset: Vec3) -> Self: ...
    def rotate(
        self,
        angle: float,
        axis: Vec3 = OUT,
        about_point: Vec3 | None = None,
    ) -> Self: ...
    def scale(
        self,
        factor: float,
        about_point: Vec3 | None = None,
    ) -> Self: ...
    def move_to(
        self,
        target: "Vec3 | Mobject",
        aligned_edge: Vec3 = ORIGIN,
        coor_mask: Vec3 | None = None,
    ) -> Self: ...
    def next_to(
        self,
        target: "Vec3 | Mobject",
        direction: Vec3 = RIGHT,
        buff: float = 0.25,
    ) -> Self: ...
    def align_to(self, target: "Vec3 | Mobject", direction: Vec3) -> Self: ...
    def arrange(
        self,
        direction: Vec3 = RIGHT,
        buff: float = 0.25,
        center: bool = True,
    ) -> Self: ...
    def rotate_quaternion(
        self,
        quaternion: Vec4,
        about_point: Vec3 | None = None,
    ) -> Self: ...
    def scale_x(self, factor: float, about_point: Vec3 | None = None) -> Self: ...
    def scale_y(self, factor: float, about_point: Vec3 | None = None) -> Self: ...
    def scale_z(self, factor: float, about_point: Vec3 | None = None) -> Self: ...
    def scale_to_fit_width(self, width: float) -> Self: ...
    def scale_to_fit_height(self, height: float) -> Self: ...
    def scale_to_fit_depth(self, depth: float) -> Self: ...
    def stretch_to_fit_width(self, width: float) -> Self: ...
    def stretch_to_fit_height(self, height: float) -> Self: ...
    def stretch_to_fit_depth(self, depth: float) -> Self: ...

    # Geometry queries:

    def bounding_box(self) -> tuple[Vec3, Vec3]: ...
    def width(self) -> float: ...
    def height(self) -> float: ...
    def depth(self) -> float: ...
    def center(self) -> Vec3: ...
    def get_critical_point(self, direction: Vec3) -> Vec3: ...
