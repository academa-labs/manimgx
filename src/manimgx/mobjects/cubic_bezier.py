import math
from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject


def _eval_bezier(
    t: float,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> tuple[float, float]:

    u = 1 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return x, y


def _eval_bezier_tangent(
    t: float,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> tuple[float, float]:

    u = 1 - t
    tx = (
        3 * u**2 * (p1[0] - p0[0])
        + 6 * u * t * (p2[0] - p1[0])
        + 3 * t**2 * (p3[0] - p2[0])
    )
    ty = (
        3 * u**2 * (p1[1] - p0[1])
        + 6 * u * t * (p2[1] - p1[1])
        + 3 * t**2 * (p3[1] - p2[1])
    )
    return tx, ty


@dataclass(kw_only=True, eq=False)
class CubicBezier(PlanarPathMobject):
    p0: tuple[float, float] = (-1.0, 0.0)
    p1: tuple[float, float] = (-0.5, 1.0)
    p2: tuple[float, float] = (0.5, -1.0)
    p3: tuple[float, float] = (1.0, 0.0)
    thickness: float = 0.05

    def _create_planar_path(self, path: PlanarPath) -> None:
        hw = self.thickness / 2
        n_samples = 32

        samples: list[tuple[float, float, float, float]] = []
        for i in range(n_samples + 1):
            t = i / n_samples
            x, y = _eval_bezier(t, self.p0, self.p1, self.p2, self.p3)
            tx, ty = _eval_bezier_tangent(t, self.p0, self.p1, self.p2, self.p3)
            length = math.sqrt(tx * tx + ty * ty)
            if length > 0:
                nx, ny = -ty / length, tx / length
            else:
                nx, ny = 0.0, 1.0
            samples.append((x, y, nx, ny))

        x0, y0, nx0, ny0 = samples[0]
        path.move_to(x0 + hw * nx0, y0 + hw * ny0)
        for x, y, nx, ny in samples[1:]:
            path.line_to(x + hw * nx, y + hw * ny)
        for x, y, nx, ny in reversed(samples):
            path.line_to(x - hw * nx, y - hw * ny)
        path.close()
