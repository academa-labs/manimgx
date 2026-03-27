from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from manimgx.primitives.rate_functions import RateFunc, smooth
from manimgx.primitives.units import RunTime

if TYPE_CHECKING:
    from manimgx.mobjects.bases.mobject import Mobject
    from manimgx.scene import _Timeline


@dataclass(kw_only=True)
class Animation(ABC):
    run_time: RunTime = 1.0
    rate_func: RateFunc = smooth

    def __post_init__(self) -> None:
        self.run_time = max(0.0, self.run_time)

    def _scene_mobjects(self) -> "tuple[Mobject, ...]":
        """Mobjects this animation needs registered in the scene.

        This is intentionally explicit. Reference mobjects like ``Morph.target``
        should stay available to the animation without becoming visible just
        because they happen to be stored on the dataclass.
        """
        return ()

    def _register_scene_mobjects(self, builder: "_Timeline") -> None:
        for mobject in self._scene_mobjects():
            builder._register(mobject)

    def _prepare(self) -> None: ...  # noqa: B027

    @abstractmethod
    def _play(self, builder: "_Timeline", run_time: float) -> None: ...
