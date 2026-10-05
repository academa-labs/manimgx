"""Shared GIF previews: correct compositing, bounded files and evenly timed playback."""

from pathlib import Path

import pytest
from PIL import Image
from PIL.GifImagePlugin import GifImageFile
from scripts.showcase import wall

README = Path(__file__).parents[2] / "README.md"


def test_every_clip_s_box_lies_in_its_film() -> None:
    for clip in wall.CLIPS:
        left, top, right, bottom = clip.box
        assert 0 <= left < right <= wall.FILM[0], clip.name
        assert 0 <= top < bottom <= wall.FILM[1], clip.name
        assert abs((right - left) * 9 / 16 - (bottom - top)) < 1, clip.name


def test_a_box_that_leaves_its_film_is_refused() -> None:
    with pytest.raises(ValueError, match="leaves the film"):
        _ = wall.Clip("too-wide", 0, 1000, 0, 1000).box


def test_compositing_preserves_opaque_and_partially_transparent_colors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wall, "TILE", (3, 1))
    crop = Image.frombytes(
        "RGBa", (3, 1), bytes([0, 0, 0, 0, 64, 32, 16, 128, 12, 34, 56, 255])
    )
    shown = wall.composite(crop)
    assert shown.mode == "RGB"
    assert shown.tobytes() == bytes([13, 17, 23, 70, 40, 27, 12, 34, 56])


def test_resize_filters_premultiplied_pixels_before_compositing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wall, "TILE", (1, 1))
    crop = Image.frombytes("RGBa", (2, 1), bytes([255, 0, 0, 255, 0, 0, 0, 0]))
    assert wall.composite(crop).tobytes() == bytes([134, 8, 11])
    with pytest.raises(ValueError, match="premultiplied"):
        wall.composite(crop.convert("RGBA"))


@pytest.mark.parametrize("clip", wall.CLIPS, ids=lambda clip: clip.name)
def test_committed_gif_has_even_timing_and_stays_below_12_mb(clip: wall.Clip) -> None:
    path = wall.SHOWCASE / wall.name(clip)
    wall.validate(path)
    with Image.open(path) as image:
        assert isinstance(image, GifImageFile)
        total = 0
        for index in range(image.n_frames):
            image.seek(index)
            total += image.info["duration"]
            # FFmpeg uses transparency for unchanged pixels; decoded frames stay opaque.
            assert image.convert("RGBA").getchannel("A").getextrema() == (255, 255)
        assert total == 5000


@pytest.mark.parametrize(
    ("size", "frame_count", "duration", "loop", "message"),
    [
        ((3, 2), 50, 20, 0, "must be a"),
        ((2, 2), 49, 20, 0, "must loop"),
        ((2, 2), 50, 20, 1, "must loop"),
        ((2, 2), 50, 40, 0, "must last 20 ms"),
    ],
)
def test_validation_rejects_changed_playback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    frame_count: int,
    duration: int,
    loop: int,
    message: str,
) -> None:
    monkeypatch.setattr(wall, "TILE", (2, 2))
    monkeypatch.setattr(wall, "SECONDS", 1)
    images = [Image.new("RGB", size, (index, 50, 100)) for index in range(frame_count)]
    path = tmp_path / "invalid.gif"
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=loop,
    )
    with pytest.raises(ValueError, match=message):
        wall.validate(path)


def test_oversized_gif_never_replaces_the_existing_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = wall.CLIPS[0]
    path = tmp_path / wall.name(clip)
    path.write_bytes(b"previous asset")
    monkeypatch.setattr(wall, "SHOWCASE", tmp_path)
    monkeypatch.setattr(wall, "MAX_BYTES", 4)
    monkeypatch.setattr(wall, "frames", lambda _clip: [])

    def oversized(_tiles: list[Image.Image], destination: Path, _ffmpeg: str) -> None:
        destination.write_bytes(b"1234")  # even exactly the limit is refused

    monkeypatch.setattr(wall, "encode", oversized)
    with pytest.raises(ValueError, match="must be below"):
        wall.tile(clip, "ffmpeg")
    assert path.read_bytes() == b"previous asset"
    assert list(tmp_path.iterdir()) == [path]


def test_missing_ffmpeg_is_reported_before_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wall.shutil, "which", lambda _name: None)
    monkeypatch.setattr(wall, "SHOWCASE", tmp_path / "not-created")
    with pytest.raises(RuntimeError, match="Install FFmpeg"):
        wall.main()
    assert not wall.SHOWCASE.exists()


def test_the_readme_shows_every_film_linked_to_its_file() -> None:
    readme = README.read_text(encoding="utf-8")
    for clip in wall.CLIPS:
        assert (
            "https://raw.githubusercontent.com/academa-labs/manimgx/main/"
            f"docs/content/showcase/{wall.name(clip)}"
        ) in readme
        assert f"/blob/main/examples/{clip.name}.py" in readme
