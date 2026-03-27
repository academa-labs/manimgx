import math
from dataclasses import dataclass

from manimgx.mobjects.bases.planar_path import PlanarPath
from manimgx.mobjects.bases.planar_path_mobject import PlanarPathMobject


@dataclass(kw_only=True, eq=False)
class Star(PlanarPathMobject):
    n: int = 5
    outer_radius: float = 1.0
    inner_radius: float | None = None
    density: int = 2
    start_angle: float = math.tau / 4

    def __post_init__(self) -> None:
        super().__post_init__()
        self.n = max(2, self.n)
        if self.inner_radius is None:
            self.density = max(1, min((self.n - 1) // 2, self.density))

    def _compute_inner_radius(self) -> float:

        inner_angle = math.tau / (2 * self.n)
        outer_angle = math.tau * self.density / self.n
        inverse_x = 1 - math.tan(inner_angle) * (
            (math.cos(outer_angle) - 1) / math.sin(outer_angle)
        )
        return self.outer_radius / (math.cos(inner_angle) * inverse_x)

    def _create_planar_path(self, path: "PlanarPath") -> None:
        inner_r = (
            self.inner_radius
            if self.inner_radius is not None
            else self._compute_inner_radius()
        )
        angle_step = math.tau / self.n
        half_step = angle_step / 2

        vertices: list[tuple[float, float]] = []
        for i in range(self.n):
            outer_angle = self.start_angle + angle_step * i
            vertices.append(
                (
                    self.outer_radius * math.cos(outer_angle),
                    self.outer_radius * math.sin(outer_angle),
                )
            )
            inner_angle = self.start_angle + angle_step * i + half_step
            vertices.append(
                (
                    inner_r * math.cos(inner_angle),
                    inner_r * math.sin(inner_angle),
                )
            )

        path.polygon(vertices)
