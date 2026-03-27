import functools
import pathlib
from dataclasses import dataclass

import numpy as np
from PIL import Image as PILImage

from manimgx.engine import Material, Mesh, Surface, Texture, build_textured_quad
from manimgx.mobjects.bases.mobject import Mobject
from manimgx.primitives.color import Opacity


@dataclass(kw_only=True, eq=False)
class Image(Mobject):
    path: str | pathlib.Path
    height: float | None = None
    width: float | None = None
    opacity: Opacity = 1.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _, pw, ph = self._image_data
        aspect = pw / ph
        if self.width is not None and self.height is not None:
            w, h = self.width, self.height
        elif self.width is not None:
            w, h = self.width, self.width / aspect
        elif self.height is not None:
            w, h = self.height * aspect, self.height
        else:
            w, h = 2.0 * aspect, 2.0
        self.scale_vec = np.array([w, h, 1.0])
        self._init_mesh_instances()

    def _init_mesh_instances(self) -> None:
        mesh, texture = self._image_mesh
        self._image = self._add_direct_mesh_instance(
            Surface(mesh, Material(texture=texture))
        )
        self._image.material.opacity = max(0.0, min(1.0, self.opacity))

    @functools.cached_property
    def _image_data(self) -> tuple[list[bytes], int, int]:
        img = PILImage.open(self.path)
        pw, ph = img.size
        n_frames = getattr(img, "n_frames", 1)
        frames: list[bytes] = []
        for i in range(n_frames):
            img.seek(i)
            frame = img.convert("RGBA")
            frame = frame.transpose(PILImage.Transpose.FLIP_TOP_BOTTOM)
            frames.append(frame.tobytes())
        return frames, pw, ph

    @functools.cached_property
    def _image_mesh(self) -> tuple[Mesh, Texture]:
        frames, pw, ph = self._image_data
        return build_textured_quad(frames, pw, ph)
