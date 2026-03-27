from dataclasses import dataclass

from manimgx.mobjects.bases.typst_mobject import DEFAULT_FONT_SIZE
from manimgx.mobjects.tex import Tex
from manimgx.primitives.color import Color


@dataclass(kw_only=True, init=False, eq=False)
class MathTex(Tex):
    def __init__(
        self,
        *tex_strings: str,
        color: Color = "white",
        fill_color: Color | None = None,
        font_size: int = DEFAULT_FONT_SIZE,
    ) -> None:
        super().__init__(
            *tex_strings,
            arg_separator=" ",
            color=color,
            fill_color=fill_color,
            font_size=font_size,
            stroke_opacity=0.0,
        )
