from dataclasses import dataclass

from manimgx.animations.fade_in import _FadeBase


@dataclass
class FadeOut(_FadeBase):
    def _opacity_factor(self, alpha: float) -> float:
        return 1.0 - alpha
