import math
from dataclasses import dataclass

import numpy as np

from manimgx.mobjects.bases.surface_mobject import Surface, SurfaceMobject


@dataclass(kw_only=True, eq=False)
class Torus(SurfaceMobject):
    major_radius: float = 1.0
    minor_radius: float = 0.3
    u_resolution: int = 48
    v_resolution: int = 24

    def _create_surface(self, surface: Surface) -> None:
        major_radius = self.major_radius
        minor_radius = self.minor_radius

        def profile(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            phi = v * 2 * math.pi
            return major_radius + minor_radius * np.cos(phi), minor_radius * np.sin(phi)

        surface.revolve(
            profile,
            u_resolution=self.u_resolution,
            v_resolution=self.v_resolution,
        )
