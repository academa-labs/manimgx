"""The README's wall (`scripts/showcase/wall.py`): every clip's box lies in its film, its
frames last the loop exactly, so that it loops in time, and the README shows every film's
tiles, linked to its file."""

from pathlib import Path

import pytest
from scripts.showcase import wall

README = Path(__file__).parents[2] / "README.md"


def test_every_clip_s_box_lies_in_its_film() -> None:
    for clip in wall.CLIPS:
        left, top, right, bottom = clip.box
        assert 0 <= left < right <= wall.FILM[0], clip.name
        assert 0 <= top < bottom <= wall.FILM[1], clip.name
        assert abs((right - left) * 9 / 16 - (bottom - top)) < 1, clip.name  # 16:9


def test_a_box_that_leaves_its_film_is_refused() -> None:
    with pytest.raises(ValueError, match="leaves the film"):
        _ = wall.Clip("too-wide", 0, 1000, 0, 1000).box


def test_the_frames_last_the_loop_exactly() -> None:
    durations = wall.durations()
    assert len(durations) == wall.FPS * wall.SECONDS
    assert sum(durations) == 1000 * wall.SECONDS
    assert max(durations) - min(durations) <= 1  # whole milliseconds, evenly spread


def test_the_readme_shows_every_film_linked_to_its_file() -> None:
    readme = README.read_text(encoding="utf-8")
    for clip in wall.CLIPS:
        for scale in wall.SCALES:
            tile = f"https://manimgx.academa.ai/showcase/{wall.name(clip, scale)}"
            assert tile in readme
        assert f"/blob/main/examples/{clip.name}.py" in readme
