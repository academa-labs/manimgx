"""Feed the player: shapes once, then one 336-byte record per object and frame.

A shape is uploaded as its object defines it, and the player derives what drawing needs. A path
goes as control points in its own space, with its subpaths as curve ranges, so a reveal is a
window over u = curve index + t, and the player flattens curves at the size they are drawn; a
mesh goes as its points, texture coordinates and triangles, and the player sums its faces into
its vertices' normals (unless a surface's spline supplies them). An
upload is named by content and resource kind (`digest`), so identical resources upload once.
A record is an object's blend terms (two shape keys, two 3×4 matrices), reveal window, brushes,
widths and flags; the camera is one 4×4 matrix."""

import functools
import itertools
import struct
import weakref
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

import numpy as np

from manimgx import _engine
from manimgx._engine import digest
from manimgx.caches import Memo, forgets
from manimgx.constants import CapStyleType, LineJointType
from manimgx.drawing.geometry import (
    IDENTITY,
    Blend,
    Lattice,
    Shape,
    grid_triangles,
    subpath_ranges,
)
from manimgx.drawing.paint import linear_light, stretch_array
from manimgx.mobject import MeshMobject, PMobject, VMobject
from manimgx.mobjects.images import ImageMobject
from manimgx.mobjects.lights import (
    EnvironmentLight,
    Light,
    PointLight,
    SpotLight,
    SunLight,
)

if TYPE_CHECKING:
    from manimgx.mobject import Mobject
    from manimgx.scene import Camera

# a camera's view, drawn into a texture that later views sample by its key:
# (key, width, height, view, records)
type CameraView = tuple[int, int, int, bytes, bytes]

KEEP = 120  # frames a shape stays resident after the last frame that showed it
SWEEP = 240  # frames between evictions
MARK = 16  # frames between marking what the frame shows (see `sweep`)
BUDGET = 768 << 20  # living bytes (shapes, rows, textures) before the stale go at once
NEAR = 0.05
ON_3D = 1e-6  # a share of a depth (8 of its f32 steps): a path this near behind a mesh lies on it
OVERLAY, LIT = 1, 4
# an image's reconstruction by its resampling algorithm (the player's flags; linear: none)
NEAREST, CUBIC = 16, 32
_RECONSTRUCTION = {0: NEAREST, 2: 0, 3: CUBIC}
# a stroke's style, in the flags from bit 6 (cap | joint << 2): AUTO is a butt cap and a miter
# joint (a bevel past the miter limit, 10), for every path
CAPS = {
    CapStyleType.AUTO: 0,
    CapStyleType.BUTT: 0,
    CapStyleType.ROUND: 1 << 6,
    CapStyleType.SQUARE: 2 << 6,
}
JOINTS = {
    LineJointType.AUTO: 0,
    LineJointType.MITER: 0,
    LineJointType.ROUND: 1 << 8,
    LineJointType.BEVEL: 2 << 8,
}
_FEEDERS = itertools.count(1)
# paint 2 (fill2 … stroke_rows2) is mixed in by dash[3]: a tween's paint, mixed by the player
RECORD = np.dtype(
    [
        ("key1", "<u8"),
        ("key2", "<u8"),
        ("fill_rows", "<u8"),
        ("stroke_rows", "<u8"),
        ("fill_rows2", "<u8"),
        ("stroke_rows2", "<u8"),
        ("texture", "<u8"),
        ("flags", "<u8"),
        ("m1", "<f4", (3, 4)),
        ("m2", "<f4", (3, 4)),
        ("fill", "<f4", 4),
        ("stroke", "<f4", 4),
        ("background", "<f4", 4),
        ("fill2", "<f4", 4),
        ("stroke2", "<f4", 4),
        ("background2", "<f4", 4),
        ("params", "<f4", 4),
        ("gradient_a", "<f4", 4),
        ("gradient_b", "<f4", 4),
        ("dash", "<f4", 4),  # period, duty, phase (u); how far paint 2 is mixed in
        ("material", "<f4", 4),  # metallic, roughness, reflectance; 1 where it has one
    ]
)
assert RECORD.itemsize == 336
# a record as Python packs it: its 8 integers, its 68 floats
PACKED = struct.Struct("<8Q68f")
NO_MATERIAL = (0.0, 0.5, 0.5, 0.0)
LIGHTS = 8  # the most lights a view takes
assert PACKED.size == RECORD.itemsize
NO_TERM = (0.0,) * 12
KEYS = ("key1", "key2", "fill_rows", "stroke_rows", "fill_rows2", "stroke_rows2")


def place(m: np.ndarray, a: np.ndarray) -> np.ndarray:
    """m ∘ a for 3×4 affine maps: a shape's placement over its affine class —
    [L | t] ∘ [A | b] = L·[A | b] + [0 | t]."""
    out = m[:, :3] @ a
    out[:, 3] += m[:, 3]
    return out


def structure(points: np.ndarray) -> list[tuple[int, int, bool]]:
    """Subpaths as curve ranges (first curve, end curve, closed), by CE's break rule."""
    return [(a // 4, b // 4, closed) for a, b, closed in subpath_ranges(points, 1e-6)]


def union(
    a: list[tuple[int, int, bool]], b: list[tuple[int, int, bool]]
) -> list[tuple[int, int, bool]]:
    """The subpaths of a morph between two aligned shapes: a break wherever either breaks, closed
    only where both are."""
    starts = sorted({s for s, _, _ in a} | {s for s, _, _ in b})
    end = max(e for _, e, _ in a + b)
    closed_a = {(s, e) for s, e, c in a if c}
    closed_b = {(s, e) for s, e, c in b if c}
    spans = list(zip(starts, starts[1:] + [end], strict=True))
    return [(s, e, (s, e) in closed_a and (s, e) in closed_b) for s, e in spans]


def control(
    points: np.ndarray, ranges: list[tuple[int, int, bool]]
) -> tuple[bytes, bytes]:
    """(control points, subpaths) of one path shape as the player takes them: float64 x, y, z per
    control point, four per curve; (first curve, end curve, closed, 0) per subpath."""
    whole = points[: len(points) // 4 * 4]
    subpaths = np.array([(c0, c1, int(closed), 0) for c0, c1, closed in ranges], "<u4")
    return np.ascontiguousarray(whole, "<f8").tobytes(), subpaths.tobytes()


def centroid_area(points: np.ndarray) -> list[float]:
    """Mean of the control points and their Newell area vector (one closed polygon)."""
    nxt = np.roll(points, -1, axis=0)
    area = np.array(
        [
            np.sum((points[:, 1] - nxt[:, 1]) * (points[:, 2] + nxt[:, 2])),
            np.sum((points[:, 2] - nxt[:, 2]) * (points[:, 0] + nxt[:, 0])),
            np.sum((points[:, 0] - nxt[:, 0]) * (points[:, 1] + nxt[:, 1])),
        ]
    )
    return [*points.mean(axis=0), *area]


# ── surfaces: drawn as the C² spline through their samples ─────────────────────────
#
# A surface is its samples of func(u, v) on a grid; drawn, it is the tensor-product cubic
# spline through them (periodic along a direction whose ends meet, not-a-knot otherwise): C²,
# exact for cubics, O(h⁴) from a smooth func — a coarse grid draws the surface, not flat
# quads. Each face (a grid cell) is refined into m × m cells of its spline patch. The shape's
# midpoint deviation estimates m, capped by SURFACE_STEPS; this is not a bound on triangle
# error (a saddle can have zero midpoint deviation). Normals are the spline's. A face keeps
# its own vertices, so a checkerboard keeps its sharp
# cells, and its edge loop (4m + 1 vertices) is its outline.

# scene units: a quarter pixel at 1080p, the frame 8 units high
SURFACE_TOLERANCE = 2e-3
SURFACE_STEPS = 16  # at most, per face and direction


@forgets
@functools.cache
def _derivative(n: int, periodic: bool) -> np.ndarray:
    """(n × n) tangents, per sample step, of the C² cubic spline through n evenly spaced values:
    periodic (the last value repeats the first) or not-a-knot (below four values: the
    polynomial through them)."""
    if n < 4:
        few = [
            [[0.0]],
            [[-1.0, 1.0]] * 2,
            [[-1.5, 2, -0.5], [-0.5, 0, 0.5], [0.5, -2, 1.5]],
        ]
        return np.array(few[n - 1])
    k = n - 1 if periodic else n
    a, b, i = np.zeros((k, k)), np.zeros((k, k)), np.arange(k)
    # C²: m[i-1] + 4 m[i] + m[i+1] = 3 (p[i+1] − p[i-1])
    a[i, i], a[i, (i - 1) % k], a[i, (i + 1) % k] = 4.0, 1.0, 1.0
    b[i, (i + 1) % k], b[i, (i - 1) % k] = 3.0, -3.0
    if (
        not periodic
    ):  # not-a-knot: the third derivative is continuous at the second knots
        a[[0, -1]], b[[0, -1]] = 0.0, 0.0
        a[0, [0, 2]], b[0, :3] = [1.0, -1.0], [-2.0, 4.0, -2.0]
        a[-1, [-3, -1]], b[-1, -3:] = [-1.0, 1.0], [2.0, -4.0, 2.0]
    d = np.linalg.solve(a, b)
    return np.pad(np.vstack([d, d[:1]]), ((0, 0), (0, 1))) if periodic else d


def _hermite(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cubic Hermite bases at x (value at 0, at 1; tangent at 0, at 1) and their slopes."""
    x2, x3 = x * x, x * x * x
    value = np.stack([2 * x3 - 3 * x2 + 1, 3 * x2 - 2 * x3, x3 - 2 * x2 + x, x3 - x2])
    slope = np.stack(
        [6 * x2 - 6 * x, 6 * x - 6 * x2, 3 * x2 - 4 * x + 1, 3 * x2 - 2 * x]
    )
    return value, slope


def _cells(g: np.ndarray) -> np.ndarray:
    """Each cell's bicubic Hermite data from the spline through grid `g` ((u + 1) × (v + 1) ×
    dims): (4, 4, u, v, dims) — [value at s 0, 1; ∂u at s 0, 1] × [the same along t, ∂v].
    """
    tol = 1e-7 * (1.0 + np.abs(g[..., :3]).max())
    du = _derivative(len(g), bool(np.abs(g[0, :, :3] - g[-1, :, :3]).max() <= tol))
    dv = _derivative(g.shape[1], bool(np.abs(g[:, 0, :3] - g[:, -1, :3]).max() <= tol))
    gu = np.tensordot(du, g, axes=(1, 0))
    data = (
        (g, np.tensordot(g, dv, axes=(1, 1)).transpose(0, 2, 1)),
        (gu, np.tensordot(gu, dv, axes=(1, 1)).transpose(0, 2, 1)),
    )
    u, v = len(g) - 1, g.shape[1] - 1
    return np.array(
        [
            [
                data[i // 2][j // 2][i % 2 : u + i % 2, j % 2 : v + j % 2]
                for j in range(4)
            ]
            for i in range(4)
        ]
    )


def _patches(
    cells: np.ndarray, x: np.ndarray, *, derivatives: bool = True
) -> tuple[np.ndarray, ...]:
    """Points, and when requested their derivatives, of every cell at (s, t) ∈ x × x:
    each (len(x), len(x), u, v, dims)."""
    value, slope = _hermite(x)
    a, b, u, v, dims = cells.shape
    # every cell side by side, the bases applied as matrix products (a BLAS's, not einsum's
    # loops): along t, then along s
    data = cells.reshape(a, b, u * v * dims)
    shape = (len(x), len(x), u, v, dims)
    along_t = np.matmul(value.T, data)
    points = np.tensordot(value, along_t, axes=(0, 0)).reshape(shape)
    if not derivatives:
        return (points,)
    ds = np.tensordot(slope, along_t, axes=(0, 0)).reshape(shape)
    dt = np.tensordot(value, np.matmul(slope.T, data), axes=(0, 0)).reshape(shape)
    return points, ds, dt


def refinement(shape: Shape, grid: tuple[int, int] | None) -> int:
    """A surface shape's refinement m (0: not a surface's grid, drawn as its faces), once per
    shape: its own size decides, not where a frame puts it (a morph keeps its m)."""
    if grid is None:
        return 0

    def steps() -> int:
        _, array, a = shape.affine
        return surface_steps(array.reshape(grid[0] + 1, grid[1] + 1, -1), a[:, :3])

    return _STEPS.recall((shape.key, grid), steps)


_STEPS: Memo[tuple[int, tuple[int, int]], int] = Memo(1 << 12)


def surface_steps(g: np.ndarray, linear: np.ndarray) -> int:
    """Estimate cells per face and direction from midpoint deviation after `linear`.

    SURFACE_TOLERANCE is the target of this estimate, not a guaranteed error bound;
    refinement is capped at SURFACE_STEPS and midpoint sampling can miss curvature.
    """
    mid = _patches(_cells(g[..., :3]), np.array([0.5]), derivatives=False)[0][0, 0]
    flat = (g[:-1, :-1, :3] + g[1:, :-1, :3] + g[:-1, 1:, :3] + g[1:, 1:, :3]) / 4
    deviation = float(np.linalg.norm((mid - flat) @ linear.T, axis=-1).max())
    return int(
        np.clip(np.ceil(np.sqrt(deviation / SURFACE_TOLERANCE)), 1, SURFACE_STEPS)
    )


@forgets
@functools.cache
def _face_layout(m: int) -> tuple[np.ndarray, np.ndarray]:
    """A refined face's vertices, as (p, q) on its (m + 1)² lattice — its edge loop first
    ((0,0) → (m,0) → (m,m) → (0,m) → (0,0): the face's own loop, 4m + 1 with the first
    repeated), then its inside — and its 2m² triangles, as indices into them."""
    loop = [(p, 0) for p in range(m)] + [(m, q) for q in range(m)]
    loop += [(p, m) for p in range(m, 0, -1)] + [(0, q) for q in range(m, -1, -1)]
    order = np.array(loop + [(p, q) for p in range(1, m) for q in range(1, m)])
    index = np.zeros((m + 1, m + 1), dtype=np.int64)
    distinct = (
        np.arange(len(order)) != 4 * m
    )  # the loop's last vertex repeats its first
    index[order[distinct, 0], order[distinct, 1]] = np.arange(len(order))[distinct]
    triangles = index.ravel()[grid_triangles(m, m)]
    order.flags.writeable = triangles.flags.writeable = False
    return order, triangles


def refine_surface(
    g: np.ndarray, m: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """A surface grid drawn: every face's block of the spline's points (any extra columns
    alike), their normals, the triangles, the block's size."""
    x = np.linspace(0.0, 1.0, m + 1)
    cells = _cells(g)
    points, ds, dt = _patches(cells, x)
    normal = np.cross(ds[..., :3], dt[..., :3])
    # where a direction collapses (a pole), the normal a hair inside the face
    thin = (
        np.linalg.norm(normal, axis=-1) <= 1e-10 * (1.0 + np.abs(g[..., :3]).max()) ** 2
    )
    if thin.any():
        i, j = np.nonzero(thin.any(axis=(0, 1)))
        _, ds, dt = _patches(cells[:, :, i, j][:, :, None], 1e-3 + (1.0 - 2e-3) * x)
        nudged = np.cross(ds[..., :3], dt[..., :3])[:, :, 0]
        normal[:, :, i, j] = np.where(
            thin[:, :, i, j][..., None], nudged, normal[:, :, i, j]
        )
    order, triangles = _face_layout(m)
    block, u, v = len(order), len(g) - 1, g.shape[1] - 1
    selected = order[:, 0] * (m + 1) + order[:, 1]  # each face's block, face by face
    points = points.reshape((m + 1) ** 2, u * v, -1)[selected].transpose(1, 0, 2)
    normal = normal.reshape((m + 1) ** 2, u * v, 3)[selected].transpose(1, 0, 2)
    return (
        points.reshape(u * v * block, -1),
        normal.reshape(u * v * block, 3),
        (triangles[None] + np.arange(u * v)[:, None, None] * block).reshape(-1, 3),
        block,
    )


def rotation(phi: float, theta: float, gamma: float) -> np.ndarray:
    """CE's camera orbit: world → camera axes."""

    def rz(a: float) -> np.ndarray:
        return np.array(
            [[np.cos(a), -np.sin(a), 0.0], [np.sin(a), np.cos(a), 0.0], [0.0, 0.0, 1.0]]
        )

    c, s = np.cos(-phi), np.sin(-phi)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    return rz(gamma) @ rx @ rz(-theta - np.pi / 2)


def lighting(camera: "Camera", lights: "list[Light]") -> list[float]:
    """A view's lights, four vectors each, `LIGHTS` of them (the first ones): where (an ambient
    light: nowhere; a sun: its direction; a point or spot: its point; an environment: its
    picture's right) and its kind; its color in linear light times its intensity, and a
    point's or spot's reach (an environment: its picture's id, 0 the studio); a spot's axis
    (an environment: its picture's up) and the scale and offset of its cone's falloff,
    and whether it casts shadows (an environment: its picture's sun, which the engine
    lights by as a sun of the view's). A scene with no lights has the camera's: a sun
    from its light source, and a dim ambient light (as Manim's shading always has its light).
    """
    if not lights:
        sun = np.asarray(camera.light_source.get_center(), dtype=float)
        sun = sun / max(float(np.linalg.norm(sun)), 1e-9)
        out = [*sun, 1.0, 1.0, 1.0, 1.0, 0.0, *[0.0] * 8]  # a white sun
        out += [
            0.0,
            0.0,
            0.0,
            0.0,
            0.1,
            0.1,
            0.1,
            0.0,
            *[0.0] * 8,
        ]  # an ambient light, 0.1
        return out + [0.0] * (16 * LIGHTS - len(out))
    out = []
    for light in lights[:LIGHTS]:
        place = np.asarray(light.get_center(), dtype=float)
        color = [*(linear_light(light.light_color.to_rgb()) * light.intensity)]
        if isinstance(light, EnvironmentLight):
            right, up = light.axes()
            picture = 0.0 if light.picture is None else float(light.picture.id)
            out += [
                *right,
                4.0,
                *color,
                picture,
                *up,
                0.0,
                0.0,
                float(light.shadows),
                0,
                0,
            ]
            continue
        axis, scale, offset = np.zeros(3), 0.0, 0.0
        if isinstance(light, SunLight):
            place = place / max(float(np.linalg.norm(place)), 1e-9)
        if isinstance(light, SpotLight):
            axis = light.toward - place
            axis = axis / max(float(np.linalg.norm(axis)), 1e-9)
            outer = np.cos(light.angle)
            inner = np.cos(light.angle * (1.0 - light.softness))
            scale = 1.0 / max(inner - outer, 1e-4)
            offset = -outer * scale
        reach = light.radius if isinstance(light, PointLight) else 0.0
        shadows = isinstance(light, (SunLight, SpotLight)) and light.shadows
        out += [
            *place,
            float(light.kind),
            *color,
            reach,
            *axis,
            scale,
            offset,
            float(shadows),  # (the engine fits its shadow map)
            0.0,
            0.0,
        ]
    return out + [0.0] * (16 * LIGHTS - len(out))


def view(
    camera: "Camera", width: int, height: int, lights: "list[Light] | None" = None
) -> tuple[bytes, np.ndarray, bool]:
    """(uniform bytes, world → clip matrix, 3D?) of a camera; 2D is orthographic, so the painter's
    order stands. Reads only the camera's mobjects (`get_mobjects_indicating_movement`) and settings,
    and the view's `lights` (a 3D view's: those that light the mobjects with a material).
    """
    hw, hh = camera.frame_width / 2, camera.frame_height / 2
    center = np.asarray(camera.frame_center, dtype=float)
    three_d = bool(camera.three_d)
    overlay = np.diag([1 / hw, 1 / hh, 0.0, 1.0])
    if three_d:
        r = rotation(camera.get_phi(), camera.get_theta(), camera.get_gamma())
        zoom, f = camera.get_zoom(), camera.get_focal_distance()
        rc = r @ center
        projection = np.array(
            [
                [*(zoom / hw * r[0]), -zoom / hw * rc[0]],
                [*(zoom / hh * r[1]), -zoom / hh * rc[1]],
                # reversed Z: depth NEAR / distance (1 at the near plane, 0 at infinity): a
                # float depth's digits where things are far, as the composite's own depths
                [0.0, 0.0, 0.0, NEAR / f],
                [*(-r[2] / f), (f + rc[2]) / f],
            ]
        )
        toward, bias = r[2], ON_3D
        eye = [*(center + f * r[2]), 1.0]
    else:
        eye = [0.0, 0.0, 0.0, 0.0]
        zoom = 1.0
        projection = np.array(
            [
                [1 / hw, 0, 0, -center[0] / hw],
                [0, 1 / hh, 0, -center[1] / hh],
                [0, 0, 0, 0.5],
                [0, 0, 0, 1.0],
            ]
        )
        toward, bias = np.array([0.0, 0.0, 1.0]), 0.0
    uniform = np.concatenate(
        [
            projection.T.ravel(),  # WGSL matrices are column-major
            overlay.T.ravel(),
            [width, height, height / camera.frame_height, zoom],
            [*camera.light_source.get_center(), float(three_d)],
            [*toward, bias],
            camera.background_color.to_rgba_with_alpha(camera.background_opacity),
            # where it sees from (3D), then its lights: how many, the exposure, the tone mapping,
            # the bloom
            eye,
            [
                (min(len(lights), LIGHTS) if lights else 2) if three_d else 0,
                camera.exposure,
                float(camera.tone_mapping == "agx"),
                camera.bloom if three_d else 0.0,
            ],
            lighting(camera, lights or []) if three_d else [0.0] * (16 * LIGHTS),
            # its ambient occlusion: how much (0: none), how far around
            [
                camera.ambient_occlusion if three_d else 0.0,
                camera.ambient_occlusion_radius,
                0.0,
                0.0,
            ],
        ]
    ).astype("<f4")
    return uniform.tobytes(), projection, three_d


Player: type[_engine.Player] | None = getattr(_engine, "Player", None)
"""The engine's player, which draws with the GPU; None in Pyodide, whose engine has no GPU (a
film is then recorded as a take, with a `Recorder`)."""


class Store(Protocol):
    """What a feed uploads to, by key: the GPU's player, or a recorder writing a take. It
    takes each shape, row block, texture and environment once, grows paths, forgets what is
    evicted, and tells the bytes it holds."""

    def add_path(
        self,
        key: int,
        points: bytes,
        subpaths: bytes,
        centroid_area: Sequence[float],
        /,
    ) -> None: ...
    def add_points(self, key: int, vertices: bytes, /) -> None: ...
    def add_mesh(
        self,
        key: int,
        points: bytes,
        uvs: bytes,
        normals: bytes,
        triangles: bytes,
        outline: int,
        block: int,
        /,
    ) -> None: ...
    def add_rows(self, key: int, rows: bytes, /) -> None: ...
    def add_texture(
        self, key: int, width: int, height: int, rgba: bytes, /
    ) -> None: ...
    def add_environment(
        self, id: int, width: int, height: int, rgbe: bytes, /
    ) -> None: ...
    def grow_path(self, key: int, points: bytes, closed: bool, /) -> None: ...
    def evict(self, keys: Sequence[int], /) -> None: ...
    def held(self) -> int: ...


class Feeder:
    """Turns a frame's display list into player records, uploading what appears the first time:
    to the GPU's player, or to a recorder writing them into a take."""

    def __init__(self, width: int, height: int, player: Store) -> None:
        self.player = player
        self.serial = next(_FEEDERS)  # records kept on objects are this feeder's
        self.width, self.height = width, height
        # key → a resident shape's size: path curves (-1: nothing), cloud points, or
        # mesh vertices; rows and textures use zero, as only their presence is read
        self.sizes: dict[int, int] = {}
        # key → a resident path's subpaths (first curve, end curve, closed)
        self.structures: dict[int, list[tuple[int, int, bool]]] = {}
        self.pairs: dict[tuple[int, int], list[int]] = {}
        self.environments: set[int] = (
            set()
        )  # the environment pictures the player has, by id
        # id(texture array) → (the array, its key): kept, so no other array takes its id
        self.textures: dict[int, tuple[np.ndarray, int]] = {}
        # id(read-only rows) → (rows, key)
        self.row_keys: dict[int, tuple[np.ndarray, int]] = {}
        # a camera whose view is a texture → its number, in the order the film first drew
        # it: its texture's key (a film's keys are the same however often it is made)
        self.cameras: weakref.WeakKeyDictionary[Camera, int] = (
            weakref.WeakKeyDictionary()
        )
        self.camera_numbers = itertools.count()
        # id(shape) → (shape, topology, uvs, steps, key, A): the mesh's upload inputs.
        self.mesh_keys: dict[
            int,
            tuple[
                Shape,
                np.ndarray | Lattice,
                np.ndarray | None,
                int,
                int,
                np.ndarray,
            ],
        ] = {}
        # (id(rows), key) → (rows, a row per vertex of the refined surface `key`)
        self.expanded: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        # a growing path, by log — uploaded whole once, then only the curves it gains
        self.logs: dict[int, tuple[int | None, int]] = {}
        # a growing path's name → the key of the upload holding it (one for equal paths)
        self.holding: dict[int, int] = {}
        self.frames = 0  # frames made so far
        # key → the last frame that showed (or uploaded) it
        self.last_used: dict[int, int] = {}
        self.swept = 0
        # sweeps that evicted: a record made since draws only what is resident
        self.evictions = 0
        # the records of the film's last frame made, and of its camera views (not a picture's)
        self.latest: list[bytes] = []

    # ── residency ────────────────────────────────────────────────────────────
    def shown(self, records: np.ndarray, last: int) -> None:
        """The keys these records draw stay resident at least until frame `last` + KEEP."""
        keys = np.concatenate([records[name] for name in (*KEYS, "texture")]).tolist()
        self.last_used.update(dict.fromkeys(keys, last))
        self.last_used.pop(0, None)

    def sweep(self, pinned: Sequence[bytes] = (), *, pressed: bool = False) -> None:
        """Evict what no frame has shown for KEEP frames (frames mark what they show every MARK
        frames; the film holds back at most one frame). Memory pressure keeps only the latest
        frame and the records pinned by the caller, including every pending camera view.
        The player evicts in turn: after the frames sent before, and once its video's frames
        in flight that may be drawn again are settled."""
        pressed |= self.player.held() > BUDGET
        if self.frames - self.swept < SWEEP and not pressed:
            return
        for data in (*self.latest, *pinned):
            self.shown(np.frombuffer(data, RECORD), self.frames)
        self.swept = self.frames
        keep = 0 if pressed else KEEP
        stale = [k for k, t in self.last_used.items() if t < self.frames - keep]
        if not stale:
            return
        # a key whose path draws nothing, or whose upload failed, never reached the player:
        # it is only forgotten
        resident = [k for k in stale if self.sizes.get(k, -1) != -1]
        if resident:
            self.player.evict(resident)
        self.evictions += 1
        gone = set(stale)
        for key in stale:
            del self.last_used[key]
            self.sizes.pop(key, None)
            self.structures.pop(key, None)
        # inputs of evicted resources are hashed again if shown again
        self.textures = {
            i: kept for i, kept in self.textures.items() if kept[1] not in gone
        }
        self.row_keys = {
            i: kept for i, kept in self.row_keys.items() if kept[1] not in gone
        }
        self.mesh_keys = {
            i: kept for i, kept in self.mesh_keys.items() if kept[4] not in gone
        }
        self.pairs = {
            ab: keys for ab, keys in self.pairs.items() if gone.isdisjoint(keys)
        }
        self.holding = {n: key for n, key in self.holding.items() if key not in gone}

    # ── uploads ──────────────────────────────────────────────────────────────
    def grown(self, shape: Shape) -> tuple[int, np.ndarray] | None:
        """A growing path (a prefix of a log seen growing), named by what it holds, as a shape is:
        uploaded whole once, then only the curves it gains, and paths that hold the same share one
        upload. It is named by its content when it first grows, then by that name and the curves
        it gains: it costs what it grows. None for an ordinary shape: a log seen once or not
        grown yet, or an earlier prefix of one."""
        log = shape.log
        assert log is not None
        points = shape.array
        curves = len(points) // 4
        state = self.logs.get(log.id)
        if state is None:
            self.logs[log.id] = (None, curves)
            return None
        held, have = state
        if curves < have or (held is None and curves == have):
            return None
        tail = np.ascontiguousarray(points[have * 4 : curves * 4], "<f8")
        if held is None:
            name = digest(b"grown", shape.key.to_bytes(8, "little"))
        elif curves > have:
            name = digest(b"grown", held.to_bytes(8, "little"), tail.tobytes())
        else:
            name = held
        key = self.holding.get(name)
        if key is None:
            # the upload holding what it held grows on, if its last subpath does (closed or
            # not, as it now ends); else, or if none holds it, the path is uploaded whole
            if (
                held is not None
                and (source := self.holding.get(held)) is not None
                and len(subpath_ranges(points[have * 4 - 4 : curves * 4], 1e-6)) == 1
            ):
                *before, (first, _, _) = self.structures[source]
                closed = bool(
                    np.allclose(points[first * 4], points[curves * 4 - 1], atol=1e-6)
                )
                self.player.grow_path(source, tail.tobytes(), closed)
                self.sizes[source] = curves
                self.structures[source] = [*before, (first, curves, closed)]
                del self.holding[held]  # it holds what it grew to now
                key = source
            else:
                ranges = structure(points)
                if not ranges:
                    return None
                # this log's own key: an upload grown in place is never named again
                key = digest(
                    b"grown", name.to_bytes(8, "little"), log.id.to_bytes(8, "little")
                )
                self.player.add_path(
                    key, *control(points, ranges), centroid_area(points)
                )
                self.sizes[key], self.structures[key] = curves, ranges
            self.holding[name] = key
        self.logs[log.id] = (name, curves)
        self.last_used[key] = self.frames
        return key, IDENTITY

    def path(self, shape: Shape) -> tuple[int, np.ndarray]:
        """(key, A): the shape's affine class, uploaded once, and where it is placed — or, for
        a path that grows, the path itself (see `grown`)."""
        if shape.log is not None and (placed := self.grown(shape)) is not None:
            return placed
        key, canonical, a = shape.affine
        if key not in self.sizes:
            self.last_used[key] = self.frames
            ranges = structure(canonical)
            if not ranges:
                self.sizes[key] = -1
                return key, a
            self.player.add_path(
                key, *control(canonical, ranges), centroid_area(canonical)
            )
            self.sizes[key], self.structures[key] = len(canonical) // 4, ranges
        return key, a

    def pair(self, a: Shape, b: Shape) -> list[tuple[int, np.ndarray]]:
        """Keys and placements of a morph pair: the classes themselves if their subpaths agree, else
        both uploaded again with the union of their subpaths (once per pair)."""
        (ka, aa), (kb, ab) = self.path(a), self.path(b)
        sa, sb = self.structures.get(ka), self.structures.get(kb)
        if sa is None or sb is None or sa == sb:
            return [
                (ka, aa),
                (kb, ab),
            ]  # (a shape that draws nothing: not drawn as a pair)
        if (ka, kb) not in self.pairs:
            shared = union(sa, sb)
            keys = []
            for tag, points in ((1, a.affine[1]), (2, b.affine[1])):
                key = digest(f"{ka}:{kb}:{tag}".encode())
                self.last_used[key] = self.frames
                self.player.add_path(
                    key, *control(points, shared), centroid_area(points)
                )
                self.sizes[key], self.structures[key] = len(points) // 4, shared
                keys.append(key)
            self.pairs[(ka, kb)] = keys
        return list(zip(self.pairs[(ka, kb)], (aa, ab), strict=True))

    def points(self, shape: Shape) -> tuple[int, np.ndarray]:
        form, array, a = shape.affine
        key = digest(b"points", form.to_bytes(8, "little"))
        if key not in self.sizes:
            self.last_used[key] = self.frames
            self.player.add_points(
                key,
                np.hstack([array, np.zeros((len(array), 1))]).astype("<f4").tobytes(),
            )
            self.sizes[key] = len(array)
        return key, a

    def mesh(
        self,
        shape: Shape,
        topology: np.ndarray | Lattice,
        uvs: np.ndarray | None,
        steps: int = 0,
    ) -> tuple[int, np.ndarray]:
        """Upload explicit triangles or lower a sample lattice to refined spline cells:
        the faces it draws, cut from its whole lattice's spline."""
        lattice = topology if isinstance(topology, Lattice) else None
        steps = steps if lattice is not None else 0
        known = self.mesh_keys.get(id(shape))
        if (
            known is not None
            and known[1] is topology
            and known[2] is uvs
            and known[3] == steps
        ):
            return known[4], known[5]
        uv = (
            np.zeros((len(shape.array), 2))
            if uvs is None
            else np.asarray(uvs, dtype=float)
        )
        form, array, a = shape.affine
        if lattice is not None:
            indices = b"grid" + struct.pack("<5I", *lattice, steps)
        else:
            tri = np.ascontiguousarray(topology, dtype="<u4")
            indices = b"triangles" + tri.tobytes()
        key = digest(form.to_bytes(8, "little"), indices, uv.tobytes())
        if key not in self.sizes:
            self.last_used[key] = self.frames
            block = outline = 0
            if lattice is not None:
                u, v, first, end = lattice
                g = np.hstack([array, uv]).reshape(u + 1, v + 1, -1)
                points, normals, faces, block = refine_surface(g, steps)
                drawn = slice(first * block, end * block)
                per = len(faces) // (u * v)  # a face's triangles
                faces = faces[first * per : end * per] - first * block
                points, normals = points[drawn], normals[drawn]
                array, uv, tri = points[:, :3], points[:, 3:], faces.astype("<u4")
                outline = 4 * steps + 1
            else:
                normals = None
            self.player.add_mesh(
                key,
                np.ascontiguousarray(array, "<f8").tobytes(),
                np.ascontiguousarray(uv, "<f8").tobytes(),
                (
                    b""
                    if normals is None
                    else np.ascontiguousarray(normals, "<f8").tobytes()
                ),
                tri.tobytes(),
                outline,
                block,
            )
            self.sizes[key] = len(array)
        if len(self.mesh_keys) > 1 << 12:
            self.mesh_keys.clear()
        self.mesh_keys[id(shape)] = (shape, topology, uvs, steps, key, a)
        return key, a

    def per_vertex(
        self, rows: np.ndarray, n: int, key: int, lattice: Lattice | None
    ) -> np.ndarray:
        """A mesh's rows, one per vertex the player draws: each drawn lattice cell's paint
        row repeats on every vertex of its refined block. No lattice: an ordinary mesh's.
        """
        count = n if lattice is None else lattice.u * lattice.v
        rows = rows if len(rows) == count else stretch_array(rows, count)
        if lattice is None:
            return rows
        known = self.expanded.get((id(rows), key))
        if known is not None:
            return known[1]
        drawn = rows[lattice.first : lattice.end]
        out = np.repeat(drawn, self.sizes[key] // max(len(drawn), 1), axis=0)
        out.flags.writeable = False
        if len(self.expanded) > 1 << 10:
            self.expanded.clear()
        self.expanded[(id(rows), key)] = (rows, out)
        return out

    def rows(self, rows: np.ndarray) -> int:
        known = self.row_keys.get(id(rows))
        if known is not None:
            return known[1]  # a paint's rows never change: hashed once
        data = np.ascontiguousarray(rows, dtype="<f4").tobytes()
        key = digest(b"rows", data)
        if key not in self.sizes:
            self.last_used[key] = self.frames
            self.player.add_rows(key, data)
            self.sizes[key] = 0
        if not rows.flags.writeable:
            if len(self.row_keys) > 1 << 12:
                self.row_keys.clear()
            self.row_keys[id(rows)] = (rows, key)
        return key

    def lights(self, mobjects: "list[Mobject]") -> "list[Light]":
        """The lights among a view's mobjects, their environments' pictures uploaded the first
        time."""
        lights = [m for m in mobjects if isinstance(m, Light)]
        for light in lights:
            p = light.picture if isinstance(light, EnvironmentLight) else None
            if p is not None and p.id not in self.environments:
                self.player.add_environment(p.id, p.width, p.height, p.rgbe)
                self.environments.add(p.id)
        return lights

    def texture(self, pixels: np.ndarray) -> int:
        known = self.textures.get(id(pixels))
        if known is not None:
            return known[1]
        data = np.ascontiguousarray(pixels, dtype=np.uint8)
        key = digest(b"texture", str(data.shape).encode(), data.tobytes())
        if key not in self.sizes:
            h, w = data.shape[:2]
            self.player.add_texture(key, w, h, data.tobytes())
            self.sizes[key] = 0
        self.last_used[key] = self.frames
        if len(self.textures) > 1 << 8:
            self.textures.clear()
        self.textures[id(pixels)] = (pixels, key)
        return key

    # ── one frame ────────────────────────────────────────────────────────────
    def frame(
        self, camera: "Camera", mobjects: "list[Mobject]"
    ) -> tuple[bytes, bytes, list[CameraView]]:
        """(view, records, camera views to draw first) of the film's next frame: the arguments
        of `Player.render`. It is the latest frame, which the film may hold back (see `sweep`).
        """
        uniform, records, cameras = self.picture(camera, mobjects)
        self.latest = [records, *[c[4] for c in cameras]]
        if self.frames % MARK == 0:
            for data in self.latest:
                self.shown(np.frombuffer(data, RECORD), self.frames)
        self.frames += 1
        return uniform, records, cameras

    def picture(
        self, camera: "Camera", mobjects: "list[Mobject]"
    ) -> tuple[bytes, bytes, list[CameraView]]:
        """(view, records, camera views to draw first) of the world now, drawn at once: not a
        frame of the film, so the latest frame, which the film may still hold back, stays the
        one a sweep keeps."""
        self.sweep()
        cameras: list[CameraView] = []
        uniform, records = self.view(camera, mobjects, self.width, self.height, cameras)
        return uniform, records, cameras

    def camera_view(
        self,
        seen_by: "Camera",
        display: "Mobject",
        camera: "Camera",
        mobjects: "list[Mobject]",
        width: int,
        height: int,
        cameras: list[CameraView],
    ) -> int:
        """The texture key of what `seen_by` sees — everything but `display` — drawn at the size
        `display` covers on screen (CE's rule), before the view that shows it."""
        number = self.cameras.get(seen_by)
        if number is None:
            number = self.cameras[seen_by] = next(self.camera_numbers)
        key = digest(b"camera", number.to_bytes(8, "little"))
        if all(c[0] != key for c in cameras):
            w = max(1, int(width * display.width / camera.frame_width))
            h = max(1, int(height * display.height / camera.frame_height))
            hidden = {id(m) for m in display.get_family()}
            uniform, records = self.view(
                seen_by, [m for m in mobjects if id(m) not in hidden], w, h, cameras
            )
            cameras.append((key, w, h, uniform, records))
        return key

    def view(
        self,
        camera: "Camera",
        mobjects: "list[Mobject]",
        width: int,
        height: int,
        cameras: list[CameraView],
    ) -> tuple[bytes, bytes]:
        uniform, _, three_d = view(camera, width, height, self.lights(mobjects))
        fixed = camera.fixed_in_frame_mobjects  # read once a view
        data = b"".join(
            [
                r
                for mob in mobjects
                if (
                    r := self.record(
                        mob, camera, three_d, mobjects, width, height, cameras, fixed
                    )
                )
            ]
        )
        return uniform, data

    def record(
        self,
        mob: "Mobject",
        camera: "Camera",
        three_d: bool,
        mobjects: "list[Mobject]",
        width: int,
        height: int,
        cameras: list[CameraView],
        fixed: "set[Mobject]",
    ) -> bytes | None:
        """One object's record (336 bytes), or None if it draws nothing. It is a function of the
        object's geometry and paint (values), a mesh's topology (indices or lattice dimensions, with uvs:
        values too), its gradient's current bounds, image sampling, camera flags and lighting.
        It is kept on the object and remade only when one of them changes (or what it draws
        was evicted); a camera's picture is remade every frame."""
        g: Blend = mob._geometry
        if not g.terms:
            return None
        p = mob.paint
        box = (
            (mob.gradient_frame or mob).boundary_box()
            if isinstance(mob, VMobject) and p.graded
            else None
        )
        state = (
            mob in fixed,
            bool(p.shade_in_3d and three_d),
            bool(p.material and three_d),
            None if box is None else box.tobytes(),
            mob.resampling_algorithm if isinstance(mob, ImageMobject) else None,
        )
        live = p.texture is not None and not isinstance(p.texture, np.ndarray)
        topology = mob._topology if isinstance(mob, MeshMobject) else None
        uvs = mob.uvs if isinstance(mob, MeshMobject) else None
        memo = mob.__dict__.get("_film_record")
        if (
            memo is not None
            and not live
            and memo[0] == self.serial
            and memo[1] is g
            and memo[2] is p
            and memo[3] == state
            and memo[7] is topology
            and memo[8] is uvs
        ):
            if memo[6] == self.evictions:  # nothing evicted since it was made
                return memo[4]
            if all(k in self.sizes for k in memo[5]):
                mob.__dict__["_film_record"] = (*memo[:6], self.evictions, *memo[7:])
                return memo[4]
        made = self.make_record(
            mob, camera, three_d, mobjects, width, height, cameras, state[0]
        )
        if made is None:
            return None
        record, keys = made
        mob.__dict__["_film_record"] = (
            self.serial,
            g,
            p,
            state,
            record,
            keys,
            self.evictions,
            topology,
            uvs,
        )
        return record

    def make_record(
        self,
        mob: "Mobject",
        camera: "Camera",
        three_d: bool,
        mobjects: "list[Mobject]",
        width: int,
        height: int,
        cameras: list[CameraView],
        fixed: bool,
    ) -> tuple[bytes, tuple[int, ...]] | None:
        """(record, the keys it draws) — see `record`; `fixed`: is it fixed in the frame?"""
        g: Blend = mob._geometry
        p = mob.paint
        # key1, key2; fill rows, stroke rows of paint 1, of paint 2; texture, flags
        head = [0, 0, 0, 0, 0, 0, 0, 0]
        params = [0.0, 0.0, 0.0, 0.0]
        gradient_a, gradient_b = [0.0] * 4, [0.0] * 4
        # a tween's paint is two, mixed by the player (see `Paint.mix`); mixed wholly, or not
        # at all, as the player reads the mix (in single precision), it is one paint alone
        fill, stroke, background = (
            p.ends("fill"),
            p.ends("stroke"),
            p.ends("background"),
        )
        dash = [0.0, 0.0, 0.0, 0.0]
        if p.mix is not None:
            if 0.0 < np.float32(p.mix[2]) < 1.0:
                dash[3] = p.mix[2]
            else:
                end = int(p.mix[2] >= 0.5)
                fill, stroke, background = (
                    (x[end], x[end]) for x in (fill, stroke, background)
                )
        terms = g.terms
        grid: tuple[int, int] | None = None
        m = 0
        for materialized in (False, True):
            if isinstance(mob, VMobject):
                if len(terms) == 2:
                    keys = self.pair(terms[0][1], terms[1][1])
                else:
                    keys = [self.path(shape) for _, shape in terms[:2]]
            elif isinstance(mob, PMobject):
                keys = [self.points(shape) for _, shape in terms[:2]]
            elif isinstance(mob, MeshMobject):
                if not materialized:
                    grid = mob.grid
                steps = [refinement(shape, grid) for _, shape in terms[:2]]
                m = max(steps) if min(steps) > 0 else 0
                keys = [
                    self.mesh(shape, mob._topology, mob.uvs, m)
                    for _, shape in terms[:2]
                ]
            else:
                return None
            counts = {self.sizes[key] for key, _ in keys}
            if len(terms) <= 2 and len(counts) == 1 and min(counts) >= 0:
                break
            if materialized:
                return None
            terms = (Blend.of(mob.points).terms[0],)
        # a surface's lattice, refined (m > 0): its faces are u's steps and own its rows
        topology = mob._topology if isinstance(mob, MeshMobject) and m > 0 else None
        lattice = topology if isinstance(topology, Lattice) else None
        if isinstance(mob, VMobject):
            lo, hi = p.window(g.n // 4)
            params = [lo, hi, p.stroke_width * 0.01, p.background_width * 0.01]
            head[7] |= CAPS[p.cap] | JOINTS[p.joint]
            if p.dash is not None:  # a periodic window, in u: (period, duty, phase)
                curves = g.n // 4
                dash[:3] = p.dash[0] * curves, p.dash[1], p.dash[2] * curves
            if p.graded:
                a, b = mob.get_gradient_start_and_end_points()
                gradient_a[:3], gradient_b[:3] = a, b
                if len(fill[0]) > 1:
                    head[2], head[4] = self.rows(fill[0]), self.rows(fill[1])
                if len(stroke[0]) > 1:
                    head[3], head[5] = self.rows(stroke[0]), self.rows(stroke[1])
        elif isinstance(mob, PMobject):
            params[:2] = p.window(g.n)
            # a point's size, in scene units: as wide as a stroke of its width
            gradient_a[3] = p.stroke_width * 0.01
            if len(fill[0]) > 1:
                head[2], head[4] = self.rows(fill[0]), self.rows(fill[1])
        else:  # a mesh: the first dispatch drew nothing else
            steps = len(mob.triangles) // (1 if lattice is None else 2)
            params = [*p.window(steps), p.stroke_width * 0.01, 0.0]
            if (
                len(fill[0]) > 1
            ):  # a color per vertex (the player reads a row per vertex)
                head[2], head[4] = (
                    self.rows(self.per_vertex(f, g.n, keys[0][0], lattice))
                    for f in fill
                )
            if isinstance(p.texture, np.ndarray):
                head[6] = self.texture(p.texture)
                if isinstance(mob, ImageMobject):
                    head[7] |= _RECONSTRUCTION[mob.resampling_algorithm]
            elif p.texture is not None:  # a camera: its view is a texture
                head[6] = self.camera_view(
                    p.texture, mob, camera, mobjects, width, height, cameras
                )
        placed: list[float] = []
        for i, ((key, a), (matrix, _)) in enumerate(zip(keys, terms[:2], strict=False)):
            head[i] = key
            placed += place(matrix, a).ravel().tolist()
        if len(placed) == 12:
            placed += NO_TERM
        if fixed:
            head[7] |= OVERLAY
        if p.shade_in_3d and three_d:
            head[7] |= LIT
        record = PACKED.pack(
            *head,
            *placed,
            *fill[0][0].tolist(),
            *stroke[0][0].tolist(),
            *background[0][0].tolist(),
            *fill[1][0].tolist(),
            *stroke[1][0].tolist(),
            *background[1][0].tolist(),
            *params,
            *gradient_a,
            *gradient_b,
            *dash,
            # how its surface reflects the scene's lights (a 3D view's)
            *(
                (p.material.metallic, p.material.roughness, p.material.reflectance, 1.0)
                if p.material is not None and three_d
                else NO_MATERIAL
            ),
        )
        # the keys it draws: shapes, rows and its texture (what must be resident to reuse it)
        return record, tuple(k for k in head[:7] if k)
