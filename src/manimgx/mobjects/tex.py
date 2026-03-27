from dataclasses import dataclass

from manimgx.mobjects.bases.typst_mobject import DEFAULT_FONT_SIZE, TypstMobject
from manimgx.primitives.color import Color, Opacity


@dataclass(kw_only=True, init=False, eq=False)
class Tex(TypstMobject):
    tex_strings: tuple[str, ...]
    arg_separator: str = ""

    def __init__(
        self,
        *tex_strings: str,
        arg_separator: str = "",
        color: Color = "white",
        fill_color: Color | None = None,
        font_size: int = DEFAULT_FONT_SIZE,
        stroke_opacity: Opacity = 1.0,
    ) -> None:
        self.tex_strings = tex_strings
        self.arg_separator = arg_separator
        super().__init__(
            color=color,
            fill_color=fill_color,
            font_size=font_size,
            stroke_opacity=stroke_opacity,
        )

    def _create_typst_source(self) -> str:
        formula = self.arg_separator.join(self.tex_strings)
        return (
            '#import "@preview/mitex:0.2.4": *\n'
            '#show math.equation: set text(weight: "regular")\n'
            f"\n#mitex(`{formula}`)\n"
        )
