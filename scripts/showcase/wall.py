"""The README and docs share six small animated AVIF previews, each linked to its film.

`uv run --frozen python -m scripts.showcase.wall` runs each film in `CLIPS` and keeps
five seconds at 50 fps, cropped around what moves and without fixed titles or readouts.
Each preview is 320 × 180 pixels on #0d1117. Premultiplied pixels are resized before
compositing, keeping translucent edges intact while avoiding an alpha channel to decode.

Pillow encodes AVIF at quality 50 and speed 6, with 4:4:4 color for thin lines. All six images
together must stay strictly below 1.2 MB, and each below 500 KB. The complete set is staged and its dimensions,
frame count, timing, opacity and budgets are validated before any published file is
replaced. The rendered images are committed and used unchanged by both pages.
`scripts/showcase/logo.py` draws their SVG logo.
"""

import importlib.util
import math
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image, features
from PIL.AvifImagePlugin import AvifImageFile

import manimgx as m
from manimgx.rendering.film import Cut, Frame

ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "examples"
SHOWCASE = ROOT / "docs" / "content" / "showcase"
FILM = 1920, 1080  # the films' size, in which the clips' boxes are
TILE = 320, 180  # one image size, shared by the README and the docs
FPS, SECONDS = 50, 5
BACKGROUND = 13, 17, 23  # #0d1117
QUALITY, SPEED = 50, 6
MAX_BYTES = 500_000  # each image, strictly less
MAX_TOTAL_BYTES = 1_200_000  # the complete wall, strictly less


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
    Clip("quadratic_formula", 9.6, 240, 60, 1440),
    Clip("fourier_pi", 5, 310, 90, 1300),
    Clip("linear_maps", 5, 0, 0, 1920),
    Clip("derivative", 17.6, 0, 0, 1920),
    Clip("complex_maps", 2.4, 0, 0, 1920),
    Clip("lorenz_attractor", 7.5, 320, 150, 1280),
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


def composite(crop: Image.Image) -> Image.Image:
    """Resize premultiplied pixels, then put them on the preview's opaque background."""
    if crop.mode != "RGBa":
        raise ValueError("the renderer's pixels must be premultiplied RGBa")
    small = np.asarray(crop.resize(TILE, Image.Resampling.LANCZOS), dtype=np.float32)
    alpha = small[..., 3:4] / 255
    rgb = small[..., :3] + np.asarray(BACKGROUND) * (1 - alpha)
    return Image.fromarray(np.clip(np.rint(rgb), 0, 255).astype(np.uint8))


def frames(clip: Clip) -> list[Image.Image]:
    """Render directly at the preview's frame rate, crop, resize and composite each frame."""
    first = math.ceil(clip.start * FPS - 1e-9)
    last = first + SECONDS * FPS
    m.config.frame_rate = FPS
    m.config.pixel_width, m.config.pixel_height = FILM
    m.config.background_opacity = 0.0
    film = scene(clip.name)
    kept: list[Image.Image] = []

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
        kept.extend([composite(crop)] * shown)

    bare = type(film.__name__, (film,), {"display_list": display_list})
    bare().render(frames=keep)
    if len(kept) != last - first:
        raise RuntimeError(f"{clip.name}: the film ends before its clip does")
    return kept


def name(clip: Clip) -> str:
    """The single animated image used by both pages for a film."""
    return f"{clip.name}.avif"


def validate(path: Path) -> None:
    """Reject an AVIF that exceeds the budget or changes the preview's playback."""
    if path.stat().st_size >= MAX_BYTES:
        raise ValueError(f"{path.name}: must be below {MAX_BYTES:,} bytes")
    with Image.open(path) as image:
        if not isinstance(image, AvifImageFile) or image.size != TILE:
            raise ValueError(f"{path.name}: must be a {TILE[0]} × {TILE[1]} AVIF")
        if image.n_frames != FPS * SECONDS:
            raise ValueError(f"{path.name}: must contain {FPS * SECONDS} frames")
        if image.mode != "RGB":
            raise ValueError(f"{path.name}: must be opaque RGB")
        for index in range(image.n_frames):
            image.seek(index)
            image.load()  # AVIF timing is populated by decoding, not by seek().
            if image.info.get("duration") != 1000 // FPS:
                raise ValueError(
                    f"{path.name}: frame {index} must last {1000 // FPS} ms"
                )
            if image.info.get("timestamp") != index * 1000 // FPS:
                raise ValueError(f"{path.name}: frame {index} starts at the wrong time")


def validate_set(paths: list[Path]) -> None:
    """Validate every image and the combined budget before publishing any of them."""
    for path in paths:
        validate(path)
    total = sum(path.stat().st_size for path in paths)
    if total >= MAX_TOTAL_BYTES:
        raise ValueError(f"the complete wall must be below {MAX_TOTAL_BYTES:,} bytes")


def encode(tiles: list[Image.Image], path: Path) -> None:
    """Encode opaque animated AVIF with evenly timed frames."""
    first, *rest = tiles
    first.save(
        path,
        format="AVIF",
        save_all=True,
        append_images=rest,
        duration=1000 // FPS,
        quality=QUALITY,
        speed=SPEED,
        subsampling="4:4:4",
        max_threads=2,
    )


def main() -> None:
    if not features.check("avif"):
        raise RuntimeError("Pillow must have AVIF support to regenerate the previews")
    SHOWCASE.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".wall-", dir=SHOWCASE) as directory:
        paths = []
        for clip in CLIPS:
            path = Path(directory) / name(clip)
            encode(frames(clip), path)
            paths.append(path)
        validate_set(paths)
        for path in paths:
            destination = SHOWCASE / path.name
            path.replace(destination)
            print(
                f"{destination.name}: {destination.stat().st_size:,} bytes", flush=True
            )


if __name__ == "__main__":
    main()
