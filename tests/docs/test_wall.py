"""Shared AVIF previews: correct compositing, bounded files and evenly timed playback."""

from pathlib import Path

import pytest
from PIL import Image
from PIL.AvifImagePlugin import AvifImageFile
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
def test_committed_avif_has_even_timing_and_stays_below_budget(clip: wall.Clip) -> None:
    path = wall.SHOWCASE / wall.name(clip)
    wall.validate(path)
    with Image.open(path) as image:
        assert isinstance(image, AvifImageFile)
        total = 0
        for index in range(image.n_frames):
            image.seek(index)
            image.load()
            assert image.info["timestamp"] == total
            total += image.info["duration"]
            assert image.mode == "RGB"
        assert total == 5000


def test_the_complete_committed_wall_stays_below_budget() -> None:
    wall.validate_set([wall.SHOWCASE / wall.name(clip) for clip in wall.CLIPS])


@pytest.mark.parametrize(
    ("size", "frame_count", "duration", "mode", "message"),
    [
        ((3, 2), 50, 20, "RGB", "must be a"),
        ((2, 2), 49, 20, "RGB", "must contain"),
        ((2, 2), 50, 40, "RGB", "must last 20 ms"),
        ((2, 2), 50, 20, "RGBA", "must be opaque RGB"),
    ],
)
def test_validation_rejects_changed_playback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    size: tuple[int, int],
    frame_count: int,
    duration: int,
    mode: str,
    message: str,
) -> None:
    monkeypatch.setattr(wall, "TILE", (2, 2))
    monkeypatch.setattr(wall, "SECONDS", 1)
    images = [
        Image.new(
            mode, size, (index, 50, 100, 128) if mode == "RGBA" else (index, 50, 100)
        )
        for index in range(frame_count)
    ]
    path = tmp_path / "invalid.avif"
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=duration,
        max_threads=2,
    )
    with pytest.raises(ValueError, match=message):
        wall.validate(path)


def test_the_per_file_budget_is_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "too-large.avif"
    path.write_bytes(b"1234")
    monkeypatch.setattr(wall, "MAX_BYTES", 4)
    with pytest.raises(ValueError, match="must be below 4 bytes"):
        wall.validate(path)


def test_the_combined_budget_is_checked_before_replacing_any_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wall, "SHOWCASE", tmp_path)
    monkeypatch.setattr(wall, "TILE", (2, 2))
    monkeypatch.setattr(wall, "SECONDS", 1)
    monkeypatch.setattr(wall, "CLIPS", wall.CLIPS[:2])
    images = [Image.new("RGB", (2, 2), (index, 50, 100)) for index in range(50)]
    monkeypatch.setattr(wall, "frames", lambda _clip: images)
    reference = tmp_path / "reference.avif"
    wall.encode(images, reference)
    wall.validate(reference)
    monkeypatch.setattr(wall, "MAX_TOTAL_BYTES", reference.stat().st_size * 2)
    reference.unlink()
    paths = [tmp_path / wall.name(clip) for clip in wall.CLIPS]
    for path in paths:
        path.write_bytes(b"previous asset")
    with pytest.raises(ValueError, match="the complete wall must be below"):
        wall.main()  # Individually valid images, whose sum equals the strict limit.
    assert all(path.read_bytes() == b"previous asset" for path in paths)
    assert set(tmp_path.iterdir()) == set(paths)


def test_a_failed_later_encode_does_not_publish_an_earlier_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wall, "SHOWCASE", tmp_path)
    monkeypatch.setattr(wall, "CLIPS", wall.CLIPS[:2])
    monkeypatch.setattr(wall, "frames", lambda _clip: [])
    paths = [tmp_path / wall.name(clip) for clip in wall.CLIPS]
    for path in paths:
        path.write_bytes(b"previous asset")

    def fail_later(_tiles: list[Image.Image], path: Path) -> None:
        if path.name == paths[-1].name:
            raise RuntimeError("encoder failed")
        path.write_bytes(b"new asset")

    monkeypatch.setattr(wall, "encode", fail_later)
    with pytest.raises(RuntimeError, match="encoder failed"):
        wall.main()
    assert all(path.read_bytes() == b"previous asset" for path in paths)
    assert set(tmp_path.iterdir()) == set(paths)


def test_missing_avif_support_is_reported_before_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wall.features, "check", lambda _name: False)
    monkeypatch.setattr(wall, "SHOWCASE", tmp_path / "not-created")
    with pytest.raises(RuntimeError, match="Pillow must have AVIF support"):
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
