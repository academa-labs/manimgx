"""A film's video: decoded, it shows the frames the film drew, in their colors — the engine's
conversion to NV12, x264 (built into the engine), and what the MP4 says of its colors agree.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import av
import numpy as np
import pytest
from tests.integration.corpus.frames import decode

import manimgx as m
from manimgx._engine import Player
from manimgx.rendering.feed import Feeder
from manimgx.rendering.film import Cut, Frame, X264Preset

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


@pytest.mark.parametrize("pixels", [False, True])
@pytest.mark.parametrize("cut", [False, True])
def test_video_and_pixel_sinks_share_one_draw(
    tmp_path: Path, pixels: bool, cut: bool
) -> None:
    player = Mock(wraps=Player(*SIZE))
    sent: list[Frame] = []

    def sink(frame: Frame) -> None:
        sent.append(frame)
        if pixels:
            assert len(frame.pixels()) == SIZE[0] * SIZE[1] * 4
        if cut and len(sent) == 3:
            raise Cut

    video = tmp_path / "shared.mp4"
    with patch("manimgx.rendering.feed.Player", return_value=player):
        Filled().render(video, frames=sink)
    assert player.push.call_count == len(sent)
    assert all(
        call.kwargs.get("capture", False) == pixels
        for call in player.push.call_args_list
    )
    player.render.assert_not_called()
    assert len(list(decode(video, SIZE))) == len(sent)
    # A frame retained by a metadata consumer must no longer try to export it when read.
    assert len(sent[-1].pixels()) == SIZE[0] * SIZE[1] * 4
    assert player.push.call_count == len(sent)


@pytest.mark.parametrize("queued_layers", [False, True])
def test_captured_exports_preserve_pixels_and_video_across_pending_draws(
    tmp_path: Path, queued_layers: bool
) -> None:
    # RGBA rows require padding; NV12 edges are partial macroblocks.
    width, height = 130, 74
    capture, plain, direct = (Player(width, height) for _ in range(3))
    feeders = [Feeder(width, height, player) for player in (capture, plain, direct)]
    camera = m.Camera(three_d=True)
    # Cover the picture in see-through mesh layers: the first draw must grow its fragment
    # lists. Capturing must return the successful retry, including after older queued draws.
    layers: list[m.Mobject] = [
        m.MeshMobject(
            np.array([[-8, -5, z], [8, -5, z], [8, 5, z], [-8, 5, z]]),
            np.array([[0, 1, 2], [0, 2, 3]]),
            color=m.BLUE if i % 2 else m.RED,
            fill_opacity=0.2,
        )
        for i, z in enumerate(np.linspace(-0.2, 0.2, 12))
    ]
    captured_video, plain_video = tmp_path / "captured.mp4", tmp_path / "plain.mp4"
    capture.begin_export(str(captured_video), 30)
    plain.begin_export(str(plain_video), 30)
    for index, wanted in enumerate([False, False, False, True, True, False, True]):
        objects = (
            layers
            if (index >= 3) != queued_layers
            else [m.Square(fill_opacity=1).shift((index % 3) * m.RIGHT)]
        )
        prepared = [feeder.frame(camera, objects) for feeder in feeders]
        expected = direct.render(*prepared[2])
        assert any(expected[0::4])  # geometry is visible, including the mesh layers
        view, records, cameras = prepared[0]
        actual = capture.push(view, records, cameras=cameras, capture=wanted)
        assert actual == (expected if wanted else None)
        view, records, cameras = prepared[1]
        assert plain.push(view, records, cameras=cameras) is None
    capture.end_export()
    plain.end_export()
    assert captured_video.read_bytes() == plain_video.read_bytes()
