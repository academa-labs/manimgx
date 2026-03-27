from dataclasses import dataclass

from manimgx.engine import Material, Mesh, Surface
from manimgx.mobjects.bases.mobject import Mobject


@dataclass(kw_only=True, init=False, eq=False)
class Group(Mobject):
    def __init__(self, *mobjects: Mobject) -> None:
        super().__init__()
        self._group = self._add_direct_mesh_instance(Surface(Mesh.empty(), Material()))
        self.add(*mobjects)
