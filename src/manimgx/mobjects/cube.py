from dataclasses import dataclass

from manimgx.mobjects.bases.surface_mobject import Surface, SurfaceMobject


@dataclass(kw_only=True, eq=False)
class Cube(SurfaceMobject):
    side_length: float = 2.0

    def _create_surface(self, surface: Surface) -> None:
        s = self.side_length
        surface.box(s, s, s)
