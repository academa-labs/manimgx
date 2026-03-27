from dataclasses import dataclass

import numpy as np

from manimgx.mobjects.bases.surface_mobject import Surface, SurfaceMobject


@dataclass(kw_only=True, eq=False)
class Cylinder(SurfaceMobject):
    radius: float = 1.0
    cyl_height: float = 2.0
    u_resolution: int = 32
    v_resolution: int = 1

    def _create_surface(self, surface: Surface) -> None:
        radius = self.radius
        cyl_height = self.cyl_height

        def profile(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            return np.full_like(v, radius), (v - 0.5) * cyl_height

        surface.revolve(
            profile,
            u_resolution=self.u_resolution,
            v_resolution=self.v_resolution,
        )
