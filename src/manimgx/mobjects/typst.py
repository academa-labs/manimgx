from dataclasses import dataclass

from manimgx.mobjects.bases.typst_mobject import DEFAULT_FONT_SIZE, TypstMobject
from manimgx.primitives.color import Color, Opacity


@dataclass(kw_only=True, init=False, eq=False)
class Typst(TypstMobject):
    formula: str

    def __init__(
        self,
        formula: str,
        *,
        color: Color = "white",
        fill_color: Color | None = None,
        font_size: int = DEFAULT_FONT_SIZE,
        stroke_opacity: Opacity = 1.0,
    ) -> None:
        self.formula = formula
        super().__init__(
            color=color,
            fill_color=fill_color,
            font_size=font_size,
            stroke_opacity=stroke_opacity,
        )

    def _create_typst_source(self) -> str:
        return self.formula
