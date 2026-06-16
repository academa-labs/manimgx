"""A film's video: decoded, it shows the frames the film drew, in their colors — the engine's
conversion to NV12, x264 (built into the engine), and what the MP4 says of its colors agree.
"""

from pathlib import Path

import av
import numpy as np
import pytest
from tests.integration.corpus.frames import decode

import manimgx as m
from manimgx.rendering.film import Frame, X264Preset

SIZE = (320, 180)
pytestmark = pytest.mark.config(pixel_width=SIZE[0], pixel_height=SIZE[1])


class Filled(m.Scene):
    def construct(self) -> None:
        self.add(m.Rectangle(width=10, height=6, color=m.ORANGE, fill_opacity=1))
        self.play(m.Create(m.Circle(color=m.TEAL)))
        self.wait(0.5)


def test_the_video_shows_the_frames_drawn(tmp_path: Path) -> None:
    drawn: list[np.ndarray] = []

    def sink(frame: Frame) -> None:
        pixels = np.frombuffer(frame.pixels(), np.uint8).reshape(SIZE[1], SIZE[0], 4)
        drawn.append(pixels[:, :, :3].astype(int))

    Filled().render(tmp_path / "filled.mp4", frames=sink)
    shown = [frame.astype(int) for frame in decode(tmp_path / "filled.mp4", SIZE)]
    assert len(shown) == len(drawn)  # a held frame is one picture that lasts
    for picture, frame in zip(shown, drawn, strict=True):
        assert np.abs(picture - frame).mean() < 1.0
    # inside the rectangle, away from the circle's stroke: its orange, within a level or two
    assert np.abs(shown[-1][90, 60] - drawn[-1][90, 60]).max() <= 2


@pytest.mark.parametrize("preset", ["ultrafast", "slow"])
def test_each_picture_shows_at_its_frame(tmp_path: Path, preset: X264Preset) -> None:
    # a slow preset encodes B-frames: pictures decoded after the picture they are shown
    # before, so the MP4 says when each is shown apart from when it is decoded
    starts: list[int] = []
    video = tmp_path / "filled.mp4"
    Filled().render(
        video, frames=lambda frame: starts.append(frame.index), preset=preset
    )
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        assert stream.time_base is not None
        shown = [
            frame.pts * stream.time_base * int(m.config.frame_rate)
            for frame in container.decode(stream)
            if frame.pts is not None
        ]
    assert shown == starts
