"""The configuration's frame: the video's proportions, with a short side of 8 units.

- Unless its height is set, the frame's short side is 8 units at every size of video, wide
  (16:9: about 14.2 × 8) or tall (9:16: 8 × about 14.2), and the frame has the video's
  proportions. A scene laid out in the central 8 × 8 square fits both, at the same size.
- A height that is set is the frame's height, whatever the video's proportions; the CLI's
  reset before a scene file forgets it, as it forgets every field.
"""

import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

import manimgx as m
from manimgx.config import Config

pixels = st.integers(16, 4096)


@given(width=pixels, height=pixels)
def test_the_frames_short_side_is_8_units_in_the_videos_proportions(
    width: int, height: int
) -> None:
    config = Config(pixel_width=width, pixel_height=height)
    assert min(config.frame_width, config.frame_height) == pytest.approx(8)
    assert config.frame_width / config.frame_height == pytest.approx(width / height)


def test_a_tall_video_is_a_wide_one_turned() -> None:
    wide = Config(pixel_width=1920, pixel_height=1080)
    tall = Config(pixel_width=1080, pixel_height=1920)
    assert (wide.frame_width, wide.frame_height) == pytest.approx((128 / 9, 8))
    assert (tall.frame_width, tall.frame_height) == pytest.approx((8, 128 / 9))


@given(width=pixels, height=pixels, set_to=st.floats(0.5, 100))
def test_a_height_set_is_the_frames_height(
    width: int, height: int, set_to: float
) -> None:
    config = Config(pixel_width=width, pixel_height=height)
    config["frame_height"] = set_to
    assert config.frame_height == set_to
    assert config.frame_width == pytest.approx(set_to * width / height)


@pytest.mark.config(pixel_width=1080, pixel_height=1920)
def test_the_defaults_forget_a_height_set() -> None:
    m.config.frame_height = 8
    for field in dataclasses.fields(Config):
        setattr(m.config, field.name, getattr(Config(), field.name))
    m.config.pixel_width, m.config.pixel_height = 1080, 1920
    assert m.config.frame_width == pytest.approx(8)
