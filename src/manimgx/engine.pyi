import pathlib
from collections.abc import Callable
from typing import ClassVar

from manimgx.primitives.vector import Vec3, Vec4

__all__ = [
    "Camera",
    "FillRule",
    "Material",
    "Mesh",
    "Object3D",
    "PathCommand",
    "Renderer",
    "Shading",
    "Side",
    "Surface",
    "SvgGlyphData",
    "TessellationResult",
    "build_surface",
    "tessellate",
    "tessellate_svg",
]

# ── Geometry & appearance ────────────────────────────────────────────

class Mesh:
    """Immutable triangulated geometry living on the GPU."""

    bounds: tuple[float, float, float, float, float, float]
    @staticmethod
    def empty() -> Mesh: ...

class Shading:
    UNLIT: ClassVar[Shading]
    FLAT: ClassVar[Shading]
    SMOOTH: ClassVar[Shading]

class Side:
    FRONT: ClassVar[Side]
    BACK: ClassVar[Side]
    BOTH: ClassVar[Side]

class Material:
    """Surface appearance — color, transparency, lighting model."""

    def __init__(
        self,
        *,
        color: tuple[int, int, int] = (255, 255, 255),
        opacity: float = 1.0,
        shading: Shading = ...,
        side: Side = ...,
        metallic: float = 0.0,
        roughness: float = 0.5,
        emissive: tuple[int, int, int] = (0, 0, 0),
    ) -> None: ...

    color: tuple[int, int, int]
    opacity: float
    shading: Shading
    side: Side
    metallic: float
    roughness: float
    emissive: tuple[int, int, int]

class Surface:
    """Geometry + appearance — **what to draw**.

    Pairs a Mesh with a Material.  Carries no transform of its own.
    Attach to an Object3D (which controls *where* it is drawn).
    """

    def __init__(self, mesh: Mesh, material: Material) -> None: ...
    @property
    def mesh(self) -> Mesh: ...
    @mesh.setter
    def mesh(self, value: Mesh) -> None: ...
    @property
    def material(self) -> Material: ...
    @material.setter
    def material(self, value: Material) -> None: ...

    active: bool
    z_index: float

# ── Scene graph ──────────────────────────────────────────────────────

class Object3D:
    """Transform + grouping — absolute scene coordinates.

    An Object3D holds one or more Surfaces (the visual layers) and
    a transform (position, scale, quaternion).  All coordinates are
    absolute — there is no local/world distinction.

    The ``parent`` link is a **grouping mechanism**: it defines "who
    moves with me" (for ``shift``/``rotate``/``apply_scale``) and
    cascading visibility.  It does NOT define a coordinate space.

    **Property setters** set this object only — no propagation::

        obj.position = np.array([1.0, 0.0, 0.0])  # just this object

    **Group-transform methods** propagate to all descendants (in Rust)::

        obj.shift(RIGHT)  # this object + all descendants
        obj.rotate(q, center)  # this object + all descendants orbit
        obj.apply_scale(s, center)  # this object + all descendants scale

    Visibility cascades: if ``active`` is False, all Surfaces on
    this object and any descendant are hidden.
    """

    def __init__(self, *surfaces: Surface) -> None: ...
    @property
    def surfaces(self) -> list[Surface]: ...

    # ── Transform (absolute scene coordinates) ───────────────────────
    @property
    def position(self) -> Vec3: ...
    @position.setter
    def position(self, value: Vec3) -> None: ...
    @property
    def scale(self) -> Vec3: ...
    @scale.setter
    def scale(self, value: Vec3) -> None: ...
    @property
    def quaternion(self) -> Vec4: ...
    @quaternion.setter
    def quaternion(self, value: Vec4) -> None: ...

    # ── Grouping ─────────────────────────────────────────────────────
    @property
    def parent(self) -> Object3D | None: ...
    @parent.setter
    def parent(self, value: Object3D | None) -> None: ...

    active: bool

    # ── Group transforms (propagate to all descendants) ──────────────
    def shift(self, offset: Vec3) -> None:
        """Shift this object and all descendants by *offset*."""

    def rotate(self, quaternion: Vec4, about: Vec3 | None = None) -> None:
        """Rotate this object and all descendants.

        *about* defaults to this object's position (rotate in place,
        descendants orbit around this object).
        """

    def apply_scale(self, factor: Vec3, about: Vec3 | None = None) -> None:
        """Scale this object and all descendants.

        *about* defaults to this object's position (scale outward from
        this object).
        """

class Camera:
    """Controls the visible region and viewpoint."""

    def __init__(
        self,
        *,
        frame_height: float = 8.0,
        background: tuple[int, int, int] = (0, 0, 0),
    ) -> None: ...

    frame_height: float
    background: tuple[int, int, int]
    projection: int  # 0 = orthographic (default), 1 = perspective
    fov: float  # degrees, used when projection=1

    @property
    def position(self) -> Vec3: ...
    @position.setter
    def position(self, value: Vec3) -> None: ...
    @property
    def quaternion(self) -> Vec4: ...
    @quaternion.setter
    def quaternion(self, value: Vec4) -> None: ...

class Renderer:
    """Drives the Metal GPU pipeline.

    1. Create Object3Ds with Surfaces and add them.
    2. Set a Camera.
    3. Call render — the engine calls evaluate_frame(time) for each frame,
       you mutate Material/Object3D/Camera properties, the engine draws.
    """

    def __init__(self) -> None: ...
    def add(self, object3d: Object3D) -> None: ...
    def set_camera(self, camera: Camera) -> None: ...
    def render(
        self,
        *,
        evaluate_frame: Callable[[float], None],
        total_duration: float,
        output: pathlib.Path,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        supersample: int = 1,
    ) -> None: ...

# ── Tessellation (2D paths → Mesh) ─────────────────────────────────

class PathCommand:
    """SVG-style path verbs for tessellate()."""

    MOVE_TO: ClassVar[int]
    LINE_TO: ClassVar[int]
    CUBIC_TO: ClassVar[int]
    QUAD_TO: ClassVar[int]
    CLOSE: ClassVar[int]

class FillRule:
    NON_ZERO: ClassVar[FillRule]
    EVEN_ODD: ClassVar[FillRule]

class TessellationResult:
    """Output of tessellate() — separate fill and stroke meshes."""

    @property
    def fill_mesh(self) -> Mesh | None: ...
    @property
    def stroke_mesh(self) -> Mesh | None: ...

class SvgGlyphData:
    """One glyph from tessellate_svg(), preserving its original color."""

    @property
    def fill_mesh(self) -> Mesh | None: ...
    @property
    def stroke_mesh(self) -> Mesh | None: ...
    @property
    def color(self) -> tuple[int, int, int]: ...

def tessellate(
    command_types: list[int],
    command_data: list[float],
    *,
    fill_rule: FillRule = FillRule.NON_ZERO,
    stroke_width: float = 0.0,
) -> TessellationResult: ...
def tessellate_svg(svg_bytes: bytes) -> list[SvgGlyphData]: ...

# ── 3D surface builders ───────────────────────────────────────────

def build_surface(
    positions: list[float],
    normals: list[float],
    indices: list[int],
) -> Mesh: ...
