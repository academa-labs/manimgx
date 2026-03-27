from dataclasses import dataclass

from manimgx.mobjects.rectangle import Rectangle


@dataclass(kw_only=True, eq=False)
class Square(Rectangle):
    side_length: float = 2.0

    def __post_init__(self) -> None:
        self.width = self.side_length
        self.height = self.side_length
        super().__post_init__()
