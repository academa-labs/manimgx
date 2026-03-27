import functools
import math
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

import numpy as np
import numpy.typing as npt

from manimgx.engine import Material, Mesh, Object3D, Side, build_surface
from manimgx.engine import Surface as EngineSurface
from manimgx.mobjects.bases.mobject import Mobject
from manimgx.primitives.color import Color, parse_color

type ParametricFunc = Callable[
    [npt.NDArray[np.floating], npt.NDArray[np.floating]],
    tuple[npt.NDArray, npt.NDArray, npt.NDArray],
]


@dataclass(kw_only=True, eq=False)
class SurfaceMobject(Mobject):
    color: Color = "blue"
    opacity: float = 1.0

    @abstractmethod
    def _create_surface(self, surface: "Surface") -> None: ...

    @functools.cached_property
    def _object3d(self) -> Object3D:
        surface = Surface()
        self._create_surface(surface)
        surface_mesh = tesselate_surface(surface)
        return Object3D(
            EngineSurface(
                surface_mesh,
                Material(
                    side=Side.BOTH,
                    color=parse_color(self.color),
                    opacity=self.opacity,
                ),
            ),
        )

    def _on_color_change(self, value: Color) -> None:
        self._object3d.surfaces[0].material.color = parse_color(value)

    def _on_opacity_change(self, value: float) -> None:
        self._object3d.surfaces[0].material.opacity = value


@dataclass
class SurfacePatch:
    func: ParametricFunc
    u_range: tuple[float, float]
    v_range: tuple[float, float]
    u_resolution: int
    v_resolution: int


class Surface:
    __slots__ = ("_patches",)

    def __init__(self) -> None:
        self._patches: list[SurfacePatch] = []

    def parametric(
        self,
        func: ParametricFunc,
        u_range: tuple[float, float] = (0.0, 1.0),
        v_range: tuple[float, float] = (0.0, 1.0),
        u_resolution: int = 32,
        v_resolution: int = 32,
    ) -> Self:

        self._patches.append(
            SurfacePatch(func, u_range, v_range, u_resolution, v_resolution)
        )
        return self

    def revolve(
        self,
        profile: Callable[[npt.NDArray[np.floating]], tuple[npt.NDArray, npt.NDArray]],
        u_resolution: int = 32,
        v_resolution: int = 32,
    ) -> Self:

        def func(
            u: npt.NDArray[np.floating], v: npt.NDArray[np.floating]
        ) -> tuple[npt.NDArray, npt.NDArray, npt.NDArray]:
            theta = u * 2 * math.pi
            radius, z = profile(v)
            x = radius * np.cos(theta)
            y = radius * np.sin(theta)
            return x, y, z

        return self.parametric(
            func, u_resolution=u_resolution, v_resolution=v_resolution
        )

    def box(
        self,
        size_x: float = 1.0,
        size_y: float = 1.0,
        size_z: float = 1.0,
    ) -> Self:
        sizes = (size_x, size_y, size_z)

        def _face(axis: int, sign: float) -> ParametricFunc:
            a1 = (axis + 1) % 3
            a2 = (axis + 2) % 3

            def func(
                u: npt.NDArray[np.floating], v: npt.NDArray[np.floating]
            ) -> tuple[npt.NDArray, npt.NDArray, npt.NDArray]:
                coords: list[npt.NDArray] = [np.empty_like(u)] * 3
                coords[axis] = np.full_like(u, sign * sizes[axis] / 2)
                coords[a1] = (u - 0.5) * sizes[a1]
                coords[a2] = (v - 0.5) * sizes[a2]
                return coords[0], coords[1], coords[2]

            return func

        for axis in range(3):
            for sign in (1.0, -1.0):
                self.parametric(_face(axis, sign), u_resolution=1, v_resolution=1)
        return self


def tesselate_surface(surface: Surface) -> Mesh:
    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []
    vertex_offset = 0

    for patch in surface._patches:
        pos, nor, idx = tessellate_surface_patch(patch)
        positions.extend(pos)
        normals.extend(nor)
        indices.extend(i + vertex_offset for i in idx)
        vertex_offset += len(pos) // 3

    return build_surface(positions, normals, indices)


def tessellate_surface_patch(
    patch: SurfacePatch,
) -> tuple[list[float], list[float], list[int]]:
    u_res = patch.u_resolution
    v_res = patch.v_resolution

    u_vals = np.linspace(patch.u_range[0], patch.u_range[1], u_res + 1)
    v_vals = np.linspace(patch.v_range[0], patch.v_range[1], v_res + 1)
    u_grid, v_grid = np.meshgrid(u_vals, v_vals, indexing="ij")

    pos = np.stack(patch.func(u_grid, v_grid), axis=-1)
    eps = 1e-6
    du = (np.stack(patch.func(u_grid + eps, v_grid), axis=-1) - pos) / eps
    dv = (np.stack(patch.func(u_grid, v_grid + eps), axis=-1) - pos) / eps
    normals = np.cross(du, dv)
    norms = np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-10)
    normals = normals / norms

    positions = pos.reshape(-1).tolist()
    normals_flat = normals.reshape(-1).tolist()

    stride = v_res + 1
    ii, jj = np.meshgrid(range(u_res), range(v_res), indexing="ij")
    a = (ii * stride + jj).ravel()
    b = a + stride
    indices = np.column_stack([a, b, b + 1, a, b + 1, a + 1]).ravel().tolist()

    return positions, normals_flat, indices
