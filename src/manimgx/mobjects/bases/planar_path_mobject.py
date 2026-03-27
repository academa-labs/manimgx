import functools
import math
from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from manimgx.engine import (
    Material,
    Object3D,
    PathCommand,
    Side,
    Surface,
    tessellate,
)
from manimgx.mobjects.bases.mobject import Mobject
from manimgx.primitives.color import Color, parse_color

# For Manim CE compatibility:
STROKE_WIDTH_CONVERSION: float = 0.01
KAPPA = 4 / 3 * (math.sqrt(2) - 1)


@dataclass(kw_only=True, eq=False)
class PlanarPathMobject(Mobject):
    color: Color = "white"
    opacity: float = 1.0
    stroke_color: Color = "white"
    stroke_opacity: float = 1.0
    stroke_width: float = 0.0

    @abstractmethod
    def _create_planar_path(self, path: "PlanarPath") -> None: ...

    @functools.cached_property
    def _object3d(self) -> Object3D:
        path = PlanarPath()
        self._create_planar_path(path)
        tessellation = tessellate(
            path.command_types,
            path.command_data,
            stroke_width=self.stroke_width * STROKE_WIDTH_CONVERSION,
        )
        assert tessellation.fill_mesh is not None
        assert tessellation.stroke_mesh is not None
        return Object3D(
            Surface(
                tessellation.fill_mesh,
                Material(
                    side=Side.BOTH,
                    color=parse_color(self.color),
                    opacity=self.opacity,
                ),
            ),
            Surface(
                tessellation.stroke_mesh,
                Material(
                    color=parse_color(self.stroke_color),
                    opacity=self.stroke_opacity,
                ),
            ),
        )

    def _on_color_change(self, value: Color) -> None:
        self._object3d.surfaces[0].material.color = parse_color(value)

    def _on_opacity_change(self, value: float) -> None:
        self._object3d.surfaces[0].material.opacity = value

    def _on_stroke_color_change(self, value: Color) -> None:
        self._object3d.surfaces[1].material.color = parse_color(value)

    def _on_stroke_opacity_change(self, value: float) -> None:
        self._object3d.surfaces[1].material.opacity = value


# ── PlanarPath ────────────────────────────────────────────────────────


class PlanarPath:
    __slots__ = ("command_data", "command_types")

    def __init__(self) -> None:
        self.command_types: list[int] = []
        self.command_data: list[float] = []

    def _emit(self, cmd: int, *coords: float) -> Self:
        self.command_types.append(cmd)
        self.command_data.extend(coords)
        return self

    def move_to(self, x: float, y: float) -> Self:
        return self._emit(PathCommand.MOVE_TO, x, y)

    def line_to(self, x: float, y: float) -> Self:
        return self._emit(PathCommand.LINE_TO, x, y)

    def cubic_to(
        self,
        c1x: float,
        c1y: float,
        c2x: float,
        c2y: float,
        x: float,
        y: float,
    ) -> Self:
        return self._emit(PathCommand.CUBIC_TO, c1x, c1y, c2x, c2y, x, y)

    def arc_to(
        self,
        radius: float,
        start_angle: float,
        sweep_angle: float,
        *,
        cx: float = 0.0,
        cy: float = 0.0,
    ) -> Self:
        if abs(sweep_angle) < 1e-12:
            return self
        n_segments = max(1, math.ceil(abs(sweep_angle) / (math.pi / 2)))
        segment_angle = sweep_angle / n_segments
        k = (4.0 / 3.0) * math.tan(segment_angle / 4.0)
        angle = start_angle
        for _ in range(n_segments):
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            cos_end = math.cos(angle + segment_angle)
            sin_end = math.sin(angle + segment_angle)
            self.cubic_to(
                cx + radius * (cos_a - k * sin_a),
                cy + radius * (sin_a + k * cos_a),
                cx + radius * (cos_end + k * sin_end),
                cy + radius * (sin_end - k * cos_end),
                cx + radius * cos_end,
                cy + radius * sin_end,
            )
            angle += segment_angle
        return self

    def close(self) -> Self:
        return self._emit(PathCommand.CLOSE)

    def subpath(self, start: float, end: float) -> "PlanarPath":
        if end <= start or end <= 0.0:
            return PlanarPath()
        end = min(end, 1.0)
        start = max(start, 0.0)

        segments: list[tuple[int, list[float], float]] = []  # (cmd, coords, arc_len)
        data = self.command_data
        di = 0
        last_x, last_y = 0.0, 0.0
        start_x, start_y = 0.0, 0.0

        for cmd in self.command_types:
            if cmd == PathCommand.MOVE_TO:
                x, y = data[di], data[di + 1]
                di += 2
                segments.append((cmd, [x, y], 0.0))
                last_x, last_y = x, y
                start_x, start_y = x, y
            elif cmd == PathCommand.LINE_TO:
                x, y = data[di], data[di + 1]
                di += 2
                length = math.hypot(x - last_x, y - last_y)
                segments.append((cmd, [last_x, last_y, x, y], length))
                last_x, last_y = x, y
            elif cmd == PathCommand.CUBIC_TO:
                c1x, c1y = data[di], data[di + 1]
                c2x, c2y = data[di + 2], data[di + 3]
                ex, ey = data[di + 4], data[di + 5]
                di += 6
                length = cubic_arc_length(last_x, last_y, c1x, c1y, c2x, c2y, ex, ey)
                segments.append(
                    (cmd, [last_x, last_y, c1x, c1y, c2x, c2y, ex, ey], length)
                )
                last_x, last_y = ex, ey
            elif cmd == PathCommand.CLOSE:
                length = math.hypot(start_x - last_x, start_y - last_y)
                segments.append((cmd, [last_x, last_y, start_x, start_y], length))
                last_x, last_y = start_x, start_y

        total_length = sum(seg[2] for seg in segments)
        if total_length < 1e-12:
            return PlanarPath()

        target_start = start * total_length
        target_end = end * total_length

        result = PlanarPath()
        cumulative = 0.0
        first_point: tuple[float, float] | None = None
        last_emitted_x, last_emitted_y = 0.0, 0.0

        for cmd, coords, seg_len in segments:
            seg_start = cumulative
            seg_end = cumulative + seg_len
            cumulative = seg_end

            if seg_end <= target_start:
                continue  # entirely before clip region
            if seg_start >= target_end:
                break  # past clip region

            if cmd == PathCommand.MOVE_TO:
                x, y = coords[0], coords[1]
                if first_point is None:
                    result.move_to(x, y)
                    first_point = (x, y)
                    last_emitted_x, last_emitted_y = x, y
                continue

            if cmd == PathCommand.LINE_TO or cmd == PathCommand.CLOSE:
                x0, y0, x1, y1 = coords[0], coords[1], coords[2], coords[3]
                t0 = 0.0
                if seg_start < target_start:
                    t0 = (target_start - seg_start) / seg_len if seg_len > 0 else 0.0
                t1 = 1.0
                if seg_end > target_end:
                    t1 = (target_end - seg_start) / seg_len if seg_len > 0 else 1.0
                px0 = lerp(x0, x1, t0)
                py0 = lerp(y0, y1, t0)
                px1 = lerp(x0, x1, t1)
                py1 = lerp(y0, y1, t1)
                if first_point is None:
                    result.move_to(px0, py0)
                    first_point = (px0, py0)
                result.line_to(px1, py1)
                last_emitted_x, last_emitted_y = px1, py1

            elif cmd == PathCommand.CUBIC_TO:
                x0, y0, c1x, c1y, c2x, c2y, ex, ey = coords
                t0 = 0.0
                if seg_start < target_start and seg_len > 0:
                    frac = (target_start - seg_start) / seg_len
                    t0 = find_t_for_arc_fraction(
                        x0, y0, c1x, c1y, c2x, c2y, ex, ey, frac, seg_len
                    )
                t1 = 1.0
                if seg_end > target_end and seg_len > 0:
                    frac = (target_end - seg_start) / seg_len
                    t1 = find_t_for_arc_fraction(
                        x0, y0, c1x, c1y, c2x, c2y, ex, ey, frac, seg_len
                    )
                if t0 > 0:
                    _, right = split_cubic(x0, y0, c1x, c1y, c2x, c2y, ex, ey, t0)
                    x0, y0, c1x, c1y, c2x, c2y, ex, ey = right
                    t1 = (t1 - t0) / (1.0 - t0) if t0 < 1.0 else 1.0
                if t1 < 1.0:
                    left, _ = split_cubic(x0, y0, c1x, c1y, c2x, c2y, ex, ey, t1)
                    x0, y0, c1x, c1y, c2x, c2y, ex, ey = left

                if first_point is None:
                    result.move_to(x0, y0)
                    first_point = (x0, y0)
                result.cubic_to(c1x, c1y, c2x, c2y, ex, ey)
                last_emitted_x, last_emitted_y = ex, ey

        if first_point is not None:
            fx, fy = first_point
            if abs(last_emitted_x - fx) > 1e-9 or abs(last_emitted_y - fy) > 1e-9:
                result.line_to(fx, fy)
            result.close()

        return result

    def circle(self, radius: float, *, x: float = 0.0, y: float = 0.0) -> Self:
        return self.ellipse(radius, radius, x=x, y=y)

    def ellipse(
        self, x_radius: float, y_radius: float, *, x: float = 0.0, y: float = 0.0
    ) -> Self:
        kx = x_radius * KAPPA
        ky = y_radius * KAPPA
        self.move_to(x + x_radius, y)
        self.cubic_to(x + x_radius, y + ky, x + kx, y + y_radius, x, y + y_radius)
        self.cubic_to(x - kx, y + y_radius, x - x_radius, y + ky, x - x_radius, y)
        self.cubic_to(x - x_radius, y - ky, x - kx, y - y_radius, x, y - y_radius)
        self.cubic_to(x + kx, y - y_radius, x + x_radius, y - ky, x + x_radius, y)
        self.close()
        return self

    def rectangle(
        self, width: float, height: float, *, x: float = 0.0, y: float = 0.0
    ) -> Self:
        hw = width / 2
        hh = height / 2
        self.move_to(x - hw, y - hh)
        self.line_to(x + hw, y - hh)
        self.line_to(x + hw, y + hh)
        self.line_to(x - hw, y + hh)
        self.close()
        return self

    def rounded_rectangle(
        self,
        width: float,
        height: float,
        corner_radius: float,
        *,
        x: float = 0.0,
        y: float = 0.0,
    ) -> Self:
        hw = width / 2
        hh = height / 2
        r = min(corner_radius, hw, hh)
        rk = r * KAPPA
        self.move_to(x + hw - r, y + hh)
        self.cubic_to(
            x + hw - r + rk, y + hh, x + hw, y + hh - r + rk, x + hw, y + hh - r
        )
        self.line_to(x + hw, y - (hh - r))
        self.cubic_to(
            x + hw, y - (hh - r + rk), x + hw - r + rk, y - hh, x + hw - r, y - hh
        )
        self.line_to(x - (hw - r), y - hh)
        self.cubic_to(
            x - (hw - r + rk), y - hh, x - hw, y - (hh - r + rk), x - hw, y - (hh - r)
        )
        self.line_to(x - hw, y + hh - r)
        self.cubic_to(
            x - hw, y + hh - r + rk, x - (hw - r + rk), y + hh, x - (hw - r), y + hh
        )
        self.close()
        return self

    def regular_polygon(
        self, radius: float, sides: int, *, x: float = 0.0, y: float = 0.0
    ) -> Self:
        angle_step = 2 * math.pi / sides
        angle_0 = -math.pi / 2
        self.move_to(x + radius * math.cos(angle_0), y + radius * math.sin(angle_0))
        for i in range(1, sides):
            angle = angle_0 + angle_step * i
            self.line_to(x + radius * math.cos(angle), y + radius * math.sin(angle))
        self.close()
        return self

    def polygon(self, vertices: Sequence[tuple[float, float]]) -> Self:
        if len(vertices) < 3:
            return self
        self.move_to(vertices[0][0], vertices[0][1])
        for vx, vy in vertices[1:]:
            self.line_to(vx, vy)
        self.close()
        return self

    def rotate(self, angle: float) -> Self:
        if abs(angle) < 1e-12:
            return self
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        data = self.command_data
        for i in range(0, len(data), 2):
            ox, oy = data[i], data[i + 1]
            data[i] = ox * cos_a - oy * sin_a
            data[i + 1] = ox * sin_a + oy * cos_a
        return self

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        if not self.command_data:
            return (0.0, 0.0, 0.0, 0.0)
        xs = self.command_data[0::2]
        ys = self.command_data[1::2]
        return (min(xs), min(ys), max(xs), max(ys))


# ── Arc-length helpers ────────────────────────────────────────────────


def cubic_arc_length(
    x0: float,
    y0: float,
    c1x: float,
    c1y: float,
    c2x: float,
    c2y: float,
    x3: float,
    y3: float,
) -> float:
    chord = math.hypot(x3 - x0, y3 - y0)
    poly = (
        math.hypot(c1x - x0, c1y - y0)
        + math.hypot(c2x - c1x, c2y - c1y)
        + math.hypot(x3 - c2x, y3 - c2y)
    )
    if poly - chord < 1e-6:
        return (poly + chord) / 2
    left, right = split_cubic(x0, y0, c1x, c1y, c2x, c2y, x3, y3, 0.5)
    return cubic_arc_length(*left) + cubic_arc_length(*right)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def split_cubic(
    x0: float,
    y0: float,
    c1x: float,
    c1y: float,
    c2x: float,
    c2y: float,
    x3: float,
    y3: float,
    t: float,
) -> tuple[
    tuple[float, float, float, float, float, float, float, float],
    tuple[float, float, float, float, float, float, float, float],
]:
    """De Casteljau split at parameter t. Returns (left_8, right_8)."""
    q0x = lerp(x0, c1x, t)
    q0y = lerp(y0, c1y, t)
    q1x = lerp(c1x, c2x, t)
    q1y = lerp(c1y, c2y, t)
    q2x = lerp(c2x, x3, t)
    q2y = lerp(c2y, y3, t)
    r0x = lerp(q0x, q1x, t)
    r0y = lerp(q0y, q1y, t)
    r1x = lerp(q1x, q2x, t)
    r1y = lerp(q1y, q2y, t)
    sx = lerp(r0x, r1x, t)
    sy = lerp(r0y, r1y, t)
    left = (x0, y0, q0x, q0y, r0x, r0y, sx, sy)
    right = (sx, sy, r1x, r1y, q2x, q2y, x3, y3)
    return left, right


def find_t_for_arc_fraction(
    x0: float,
    y0: float,
    c1x: float,
    c1y: float,
    c2x: float,
    c2y: float,
    x3: float,
    y3: float,
    target_frac: float,
    total_len: float,
) -> float:
    """Binary search for parameter t where arc_length(0,t)/total_len ≈ target_frac."""
    target = target_frac * total_len
    lo, hi = 0.0, 1.0
    for _ in range(30):  # ~1e-9 precision
        mid = (lo + hi) / 2
        left, _ = split_cubic(x0, y0, c1x, c1y, c2x, c2y, x3, y3, mid)
        length = cubic_arc_length(*left)
        if length < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
