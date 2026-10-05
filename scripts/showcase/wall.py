"""The README and docs share six GIF previews, three a row, each linked to its film.

`uv run --frozen python -m scripts.showcase.wall` runs each film in `CLIPS` and keeps
five seconds at 50 fps, cropped around what moves and without fixed titles or readouts.
It writes `docs/content/showcase/<name>.gif`, each at 480 × 270 pixels and strictly below
12 MB. GIF delays are whole centiseconds: 20 ms gives evenly timed frames in browsers,
where a 60 fps GIF's 10 ms frames can instead be clamped to 100 ms.

The renderer's premultiplied pixels are resized before compositing onto #0d1117. GIF
cannot preserve partial transparency, so this dark background belongs to the image on
both light and dark pages. FFmpeg's global palette and Sierra dithering keep gradients
and translucent surfaces readable. Install FFmpeg and put `ffmpeg` on PATH before
regenerating. Each file replaces its predecessor only after its size, dimensions, frame
count, timing and loop setting pass validation. The rendered GIFs are committed; both
pages use those same files. `scripts/showcase/logo.py` draws their SVG logo.
"""

import importlib.util
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image
from PIL.GifImagePlugin import GifImageFile

import manimgx as m
from manimgx.rendering.film import Cut, Frame

ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "examples"
SHOWCASE = ROOT / "docs" / "content" / "showcase"
FILM = 1920, 1080  # the films' size, in which the clips' boxes are
TILE = 480, 270  # one image size, shared by the README and the docs
FPS, SECONDS = 50, 5
BACKGROUND = 13, 17, 23  # #0d1117
MAX_BYTES = 12_000_000  # strictly less, in decimal MB


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
    """Resize premultiplied pixels, then put them on the GIF's opaque background."""
    if crop.mode != "RGBa":
        raise ValueError("the renderer's pixels must be premultiplied RGBa")
    small = np.asarray(crop.resize(TILE, Image.Resampling.LANCZOS), dtype=np.float32)
    alpha = small[..., 3:4] / 255
    rgb = small[..., :3] + np.asarray(BACKGROUND) * (1 - alpha)
    return Image.fromarray(np.clip(np.rint(rgb), 0, 255).astype(np.uint8))


def frames(clip: Clip) -> list[Image.Image]:
    """Render directly at the GIF's frame rate, crop, resize and composite each frame."""
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
    """The single GIF used by both pages for a film."""
    return f"{clip.name}.gif"


def validate(path: Path) -> None:
    """Reject a GIF that exceeds the budget or changes the preview's playback."""
    if path.stat().st_size >= MAX_BYTES:
        raise ValueError(f"{path.name}: must be below {MAX_BYTES:,} bytes")
    with Image.open(path) as image:
        if not isinstance(image, GifImageFile) or image.size != TILE:
            raise ValueError(f"{path.name}: must be a {TILE[0]} × {TILE[1]} GIF")
        if image.n_frames != FPS * SECONDS or image.info.get("loop") != 0:
            raise ValueError(f"{path.name}: must loop {FPS * SECONDS} frames forever")
        for index in range(image.n_frames):
            image.seek(index)
            if image.info.get("duration") != 1000 // FPS:
                raise ValueError(
                    f"{path.name}: frame {index} must last {1000 // FPS} ms"
                )


def encode(tiles: list[Image.Image], path: Path, ffmpeg: str) -> None:
    """Encode a global palette with Sierra dithering and unchanged-pixel compression."""
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{TILE[0]}x{TILE[1]}",
            "-framerate",
            str(FPS),
            "-i",
            "pipe:0",
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            "split[a][b];[a]palettegen=max_colors=256:reserve_transparent=1[p];"
            "[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle",
            "-loop",
            "0",
            str(path),
        ],
        input=b"".join(image.tobytes() for image in tiles),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.decode(errors='replace')}")


def tile(clip: Clip, ffmpeg: str) -> None:
    """Render and validate a GIF before replacing its committed predecessor."""
    path = SHOWCASE / name(clip)
    tiles = frames(clip)
    with TemporaryDirectory(prefix=".wall-", dir=SHOWCASE) as directory:
        temporary = Path(directory) / path.name
        encode(tiles, temporary, ffmpeg)
        validate(temporary)
        temporary.replace(path)
    print(
        f"{path.name}: {len(tiles)} frames, {path.stat().st_size / 1e6:.2f} MB",
        flush=True,
    )


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "Install FFmpeg and put ffmpeg on PATH to regenerate the GIFs"
        )
    SHOWCASE.mkdir(parents=True, exist_ok=True)
    for clip in CLIPS:
        tile(clip, ffmpeg)


if __name__ == "__main__":
    main()
