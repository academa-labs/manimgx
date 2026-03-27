import math
from dataclasses import dataclass

import numpy as np

from manimgx.mobjects.bases.surface_mobject import Surface, SurfaceMobject


@dataclass(kw_only=True, eq=False)
class Sphere(SurfaceMobject):
    radius: float = 1.0
    u_resolution: int = 32
    v_resolution: int = 32

    def _create_surface(self, surface: Surface) -> None:
        radius = self.radius

        def profile(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            phi = v * math.pi
            return radius * np.sin(phi), radius * np.cos(phi)

        surface.revolve(
            profile,
            u_resolution=self.u_resolution,
            v_resolution=self.v_resolution,
        )
