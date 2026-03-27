import functools
from abc import abstractmethod
from dataclasses import dataclass

import numpy as np
import typst

from manimgx.engine import Material, Mesh, Surface, tessellate_svg
from manimgx.mobjects.bases.mobject import Mobject
from manimgx.primitives.color import Color, parse_color


@functools.cache
def _get_typst_compiler() -> typst.Compiler:
    return typst.Compiler()


DEFAULT_FONT_SIZE: int = 48

_SVG_SCALE: float = 1.0 / 140.0


@dataclass(kw_only=True, eq=False)
class TypstMobject(Mobject):
    font_size: int = DEFAULT_FONT_SIZE
    color: Color = "white"
    opacity: float = 1.0

    @abstractmethod
    def _create_typst_source(self) -> str: ...

    def _init_mesh_instances(self) -> None:
        # TypstMobject uses child FillStrokeMobjects for glyphs,
        # so it only needs an anchor mesh instance.
        self._typst = self._add_direct_mesh_instance(Surface(Mesh.empty(), Material()))

    def __post_init__(self) -> None:
        super().__post_init__()
        s = _SVG_SCALE * float(self.font_size)
        self.scale_vec = np.array([s, s, 1.0])
        self._build_glyph_children()

    def _build_glyph_children(self) -> None:
        r, g, b = parse_color(self._resolved_fill_color)
        body = self._create_typst_source()
        source = (
            "#set page(width: auto, height: auto, margin: 0.5em, fill: none)\n"
            f"#set text(fill: rgb({r}, {g}, {b}))\n"
            f"{body}"
        )
        svg_bytes = _get_typst_compiler().compile(input=source.encode(), format="svg")
        if not isinstance(svg_bytes, bytes):
            msg = "Typst compilation returned no output"
            raise RuntimeError(msg)

        for glyph in tessellate_svg(svg_bytes):
            gr, gg, gb = glyph.color
            hex_color = f"#{gr:02x}{gg:02x}{gb:02x}"
            child = FillStrokeMobject(
                fill_color=hex_color,
                fill_opacity=self.fill_opacity,
                stroke_opacity=self.stroke_opacity,
                color=hex_color,
            )
            # Override tessellation with pre-computed glyph data
            child.__dict__["_tessellation"] = glyph
            child._direct_mesh_instances.clear()
            child._init_mesh_instances()
            self.add(child)
            child.scale_vec = self.scale_vec.copy()
