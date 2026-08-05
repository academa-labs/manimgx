"""The README's wall: a moment of six example films, three a row, each its own animated image.

`python -m scripts.showcase.wall` runs each film in `CLIPS` (`examples/<name>.py`) and keeps
its moment, 25 frames a second: drawn on no background and without what the film fixes in the
frame (its titles and readouts), framed on what moves. It writes each as an animated AVIF with
alpha that loops, at a tile's size and twice it (`docs/content/showcase/<name>.avif` and
`<name>@2x.avif`, for high-density screens): GitHub and PyPI play no video but show AVIF, and
the page's own background, light or dark, shows through. The README lays them out three a row,
each linked to its film.

A browser decodes an animated image's frames on the CPU, one after another (a video's are the
GPU's), so the wall is what it can decode in time. At 60 frames a second, one image of the whole
wall showed 40 of them in Chromium, and six tiles showed some 50 on the docs site, for a core's
work; at 25 every tile shows every frame, for 0.3 to 0.4 of a core (Firefox: 0.6). A frame drawn
at half its size or less is scaled on the CPU too, hence a tile at each scale. Running the films
takes a minute, so what this writes is committed. The README's banner is the logo, which
`scripts/showcase/logo.py` draws.
"""

import importlib.util
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

import manimgx as m
from manimgx.rendering.film import Cut, Frame

ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "examples"
SHOWCASE = ROOT / "docs" / "content" / "showcase"
FILM = 1920, 1080  # the films' size, in which the clips' boxes are
TILE = 320, 180  # a tile's size in the wall, in CSS pixels
SCALES = 1, 2  # image pixels a CSS pixel: a tile for each (see the docstring)
FPS, SECONDS = 25, 5
QUALITY = 40  # AVIF's, 0 to 100: looks as 50 does, at two thirds of its bytes


@dataclass(frozen=True)
class Clip:
    """A moment of an example film: `SECONDS` from `start`, framed by the 16:9 box `width`
    pixels wide whose top left corner is (`left`, `top`), which keeps what moves."""

    name: str
    start: float
    left: int
    top: int
    width: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        """The box, as (left, top, right, bottom) in the film's pixels."""
        height = self.width * 9 // 16
        if self.left + self.width > FILM[0] or self.top + height > FILM[1]:
            raise ValueError(f"{self.name}: the box leaves the film")
        return self.left, self.top, self.left + self.width, self.top + height


CLIPS = [  # the wall's, three a row
    Clip("hopf_fibration", 17, 450, 242, 1040),
    Clip("clifford_torus", 17, 460, 306, 990),
    Clip("kaleidoscope_sphere", 5, 420, 180, 1244),
    Clip("riemann_surfaces", 17.5, 310, 234, 1300),
    Clip("turing_torus", 14, 410, 185, 1236),
    Clip("lozenge_cubes", 3.5, 249, 180, 1422),
]


def scene(name: str) -> type[m.Scene]:
    """The scene an example film's file defines."""
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = [
        v
        for v in vars(module).values()
        if isinstance(v, type) and issubclass(v, m.Scene) and v.__module__ == name
    ]
    return found[0]


def frames(clip: Clip) -> dict[int, list[Image.Image]]:
    """A clip's frames at each scale, a tile each: its film run from the beginning (only the
    clip's frames are drawn), on no background and without what it fixes in the frame,
    cropped to the clip's box and scaled to a tile. Their pixels are premultiplied, as the
    engine draws them and as the AVIF keeps them, though the images say "RGBA" (Pillow would
    otherwise unpremultiply them on the way to the encoder)."""
    first = math.ceil(clip.start * FPS - 1e-9)
    last = first + SECONDS * FPS
    m.config.frame_rate = FPS
    m.config.pixel_width, m.config.pixel_height = FILM
    m.config.background_opacity = 0.0
    film = scene(clip.name)
    kept: dict[int, list[Image.Image]] = {scale: [] for scale in SCALES}

    def display_list(self: m.Scene) -> list[m.Mobject]:
        fixed = {id(mob) for mob in self.camera.fixed_in_frame_mobjects}
        return [mob for mob in film.display_list(self) if id(mob) not in fixed]

    def keep(frame: Frame) -> None:
        if frame.index >= last:
            raise Cut
        shown = min(frame.index + frame.repeat, last) - max(frame.index, first)
        if shown <= 0:
            return
        pixels = np.frombuffer(frame.pixels(), np.uint8).reshape(FILM[1], FILM[0], 4)
        left, top, right, bottom = clip.box
        crop = Image.fromarray(pixels[top:bottom, left:right].copy(), "RGBa")
        for scale, tiles in kept.items():
            size = TILE[0] * scale, TILE[1] * scale
            small = crop.resize(
                size, Image.Resampling.LANCZOS
            )  # premultiplied, filtered
            tiles.extend([Image.frombytes("RGBA", size, small.tobytes())] * shown)

    bare = type(film.__name__, (film,), {"display_list": display_list})
    bare().render(frames=keep)
    if len(kept[1]) != last - first:
        raise RuntimeError(f"{clip.name}: the film ends before its clip does")
    return kept


def durations() -> list[int]:
    """Each frame's duration in whole milliseconds, adding up to the loop's exactly (a
    60 fps frame is 16⅔ ms: 17, 16, 17, …)."""
    ends = [round(1000 * (k + 1) / FPS) for k in range(SECONDS * FPS)]
    return [b - a for a, b in zip([0, *ends], ends, strict=False)]


def name(clip: Clip, scale: int) -> str:
    """A tile's file: the film's name, `@2x` for twice the size."""
    return f"{clip.name}.avif" if scale == 1 else f"{clip.name}@{scale}x.avif"


def tile(clip: Clip) -> None:
    """A clip as animated AVIFs with alpha, one a scale."""
    for scale, (first, *rest) in frames(clip).items():
        path = SHOWCASE / name(clip, scale)
        first.save(
            path,
            save_all=True,
            append_images=rest,
            duration=durations(),
            quality=QUALITY,
            speed=4,
            subsampling="4:2:0",
            alpha_premultiplied=True,
        )
        print(
            f"{path.name}: {1 + len(rest)} frames, {path.stat().st_size / 1e6:.2f} MB"
        )


def main() -> None:
    SHOWCASE.mkdir(parents=True, exist_ok=True)
    for clip in CLIPS:
        tile(clip)


if __name__ == "__main__":
    main()
