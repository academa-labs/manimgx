"""Inspection selects and captions the same observed frame that the film shows."""

import math
import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
import typer
from PIL import Image
from typer.testing import CliRunner

import manimgx as m
from manimgx.audio.sound import CUT, RATE, _ramp
from manimgx.cli import app, export
from manimgx.cli.export import inspect
from manimgx.cli.scenes import Format
from manimgx.cli.storyboard import Sheets


def test_inspections_distinguish_adjacent_times_and_finish_coincident_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "still_boundary.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 16\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        self.camera.background_color = m.RED\n"
        "        self.wait(0.1)\n"
        "        self.camera.background_color = m.BLUE\n"
        "        self.wait(1e-18)\n"
        "        self.wait(0.1)\n",
        encoding="utf-8",
    )
    captions: list[str] = []
    pictures: list[bytes] = []

    def keep(sheet: Sheets, text: str, picture: Image.Image) -> None:
        captions.append(text)
        pictures.append(picture.tobytes())

    monkeypatch.setattr(Sheets, "add", keep)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        inspect(
            source,
            time=[
                str(math.nextafter(0.1, 0)),
                "0.1",
                str(math.nextafter(0.1, math.inf)),
            ],
            output=tmp_path / "still.png",
        )
    finally:
        sys.modules.pop(source.stem, None)
    assert pictures[0] != pictures[1] == pictures[2]
    assert captions[0].startswith("#0 ")
    assert all(caption.startswith("#2 ") for caption in captions[1:])


def test_a_scene_error_finishes_its_storyboard_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "broken_scene.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 16\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        self.wait(0.1)\n"
        "        raise ValueError('scene failed')\n",
        encoding="utf-8",
    )
    sheets = Sheets(tmp_path / "partial.png")
    monkeypatch.setattr(export, "Sheets", lambda _: sheets)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        with pytest.raises(typer.Exit):
            export.render(source)
        assert sheets.written == [tmp_path / "partial.png"]
        assert sheets.written[0].is_file()
        with pytest.raises(RuntimeError, match="after shutdown"):
            sheets._writer.submit(lambda: None)
    finally:
        sheets._writer.shutdown()
        sys.modules.pop(source.stem, None)


def test_an_output_in_a_missing_folder_is_written_there(tmp_path: Path) -> None:
    """`-o` names where a command writes, and the folder is made as its files are written:
    the video, the storyboard and the page, each in a folder that does not exist yet."""
    source = tmp_path / "scene.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 16\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        self.wait(0.1)\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    video = tmp_path / "new" / "folder" / "out.mp4"
    result = runner.invoke(app, ["render", str(source), "-o", str(video)])
    assert result.exit_code == 0, result.output
    assert video.exists()
    assert video.with_name("out.storyboard.png").exists()
    storyboard = tmp_path / "sheets" / "sheet.png"
    result = runner.invoke(app, ["inspect", str(source), "-o", str(storyboard)])
    assert result.exit_code == 0, result.output
    assert storyboard.exists()
    deck = tmp_path / "deck" / "talk.mp4"
    result = runner.invoke(app, ["present", str(source), "-o", str(deck), "--no-open"])
    assert result.exit_code == 0, result.output
    assert deck.exists()
    assert deck.with_suffix(".html").exists()


def test_a_window_of_a_three_d_scene_shows_what_a_full_render_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A window is not only the Manim API: a lit 3D scene's environment light, a material,
    a texture, a point cloud, what is fixed in the frame, a path growing across the
    window's edge and a camera move are all the player's resources, uploaded afresh to the
    window's own film, and the frames come out the same."""
    source = tmp_path / "window_3d.py"
    source.write_text(
        "import numpy as np\n"
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 64\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.ThreeDScene):\n"
        "    def construct(self):\n"
        "        self.set_camera_orientation(phi=70 * m.DEGREES, theta=-50 * m.DEGREES)\n"
        "        self.add(m.EnvironmentLight(), m.SunLight(5 * m.UP + 3 * m.OUT))\n"
        "        self.add(m.AmbientLight(intensity=0.2))\n"
        "        ball = m.Sphere(radius=1, resolution=(32, 32)).set_color(m.GOLD)\n"
        "        self.add(ball.set_material(m.Material(metallic=1, roughness=0.25)))\n"
        "        checks = ((np.indices((8, 8)).sum(0) % 2) * 255).astype(np.uint8)\n"
        "        image = m.ImageMobject(np.dstack([checks] * 3)).scale(24)\n"
        "        self.add(image.shift(3 * m.LEFT + 2 * m.OUT))\n"
        "        self.add(m.PointCloudDot(radius=0.8).shift(2 * m.RIGHT))\n"
        "        label = m.Text('fixed', font_size=36, color=m.YELLOW).to_corner(m.UL)\n"
        "        self.add_fixed_in_frame_mobjects(label)\n"
        "        curve = m.ParametricFunction(\n"
        "            lambda t: np.array([np.cos(t), np.sin(t), t / 6]), t_range=(0, m.TAU)\n"
        "        )\n"
        "        self.play(m.Create(curve.set_color(m.BLUE)), run_time=1.5, rate_func=m.linear)\n"
        "        self.move_camera(theta=0, run_time=1.5, rate_func=m.linear)\n",
        encoding="utf-8",
    )
    full, window = tmp_path / "full.mp4", tmp_path / "window.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(source, output=full, preset="ultrafast", crf=1)
        export.render(
            source, output=window, from_=1.0, to_=2.5, preset="ultrafast", crf=1
        )
    finally:
        sys.modules.pop(source.stem, None)
    _assert_same_frames(_frames(full)[10:25], _frames(window))


@pytest.mark.parametrize(
    ("start", "sections"),
    [
        (
            10,
            [("two", 1.0, 0), ("three", 2.0, 10)],
        ),  # the window opens where "two" begins
        (15, [("two", 1.0, 0), ("three", 2.0, 5)]),  # it opens inside "two"
    ],
)
def test_a_windows_first_section_is_the_one_in_force_where_it_opens(
    tmp_path: Path, start: int, sections: list[tuple[str, float, int]]
) -> None:
    """The video begins in the section the scene is in at --from, whether that section
    begins there or earlier, and a section begun inside the window begins one of the video
    too. Each keeps its own time in the scene; the sections before the window are gone."""

    class Sectioned(m.Scene):
        def construct(self) -> None:
            self.next_section("one")
            self.wait(1)
            self.next_section("two")
            self.wait(1)
            self.next_section("three")
            self.wait(1)

    made = export.windowed(
        Sectioned,
        Format(16, 16, 10),
        tmp_path / "window.mp4",
        start,
        25,
        None,
        "ultrafast",
        1.0,
    )
    named = [(part.name, float(part.start), part.frame) for part in made.film.sections]
    assert named == sections


def _frames(path: Path) -> list[np.ndarray]:
    """Every frame `path` shows, in order (RGB), a held picture repeated for as long as it
    is shown. Counted at the video's own frame rate, as the corpus's `mp4_frames` counts at
    the corpus's: every picture lasts until the next presentation timestamp, and the last
    for its own duration."""
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        base, shown = stream.time_base, stream.average_rate
        rate = Fraction(
            base.numerator * shown.numerator, base.denominator * shown.denominator
        )
        starts: list[Fraction] = []
        pictures: list[np.ndarray] = []
        end = Fraction(0)
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            starts.append(frame.pts * rate)
            pictures.append(frame.to_ndarray(format="rgb24"))
            end = (frame.pts + frame.duration) * rate
    bounds = [*starts, end]
    assert all(bound.denominator == 1 for bound in bounds), f"{path} lasts {end} frames"
    return [
        picture
        for i, picture in enumerate(pictures)
        for _ in range(int(bounds[i + 1]) - int(bounds[i]))
    ]


def _assert_same_frames(expected: list[np.ndarray], actual: list[np.ndarray]) -> None:
    """The same pictures, pixel by pixel, give or take what the encoder rounds. The worst
    pixel is what tells them apart: a window one frame out of step differs by 255 on these
    scenes, where the same frames differ by 3."""
    assert len(actual) == len(expected)
    for i, (want, got) in enumerate(zip(expected, actual, strict=True)):
        worst = int(np.abs(want.astype(int) - got.astype(int)).max())
        assert worst <= 8, f"frame {i}: a pixel differs by {worst}"


def test_a_window_has_exactly_its_frames_even_split_from_one_pure_play(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--from 0.5 --to 1.3 at 10 fps: frames 5 up to (not including) 13, 8 of them — split
    out of one pure tween play that runs from 0 to 2 s."""
    source = tmp_path / "window_shift.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 16\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        square = m.Square()\n"
        "        self.add(square)\n"
        "        self.play(square.animate.shift(4 * m.RIGHT), run_time=2, rate_func=m.linear)\n",
        encoding="utf-8",
    )
    video = tmp_path / "window.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(source, output=video, from_=0.5, to_=1.3)
    finally:
        sys.modules.pop(source.stem, None)
    assert len(_frames(video)) == 8
    with av.open(str(video)) as container:
        assert not container.streams.audio


def test_a_window_past_the_scenes_end_is_an_error(tmp_path: Path) -> None:
    source = tmp_path / "window_short.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 16\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        self.wait(0.1)\n",
        encoding="utf-8",
    )
    video = tmp_path / "window.mp4"
    runner = CliRunner()
    result = runner.invoke(
        app, ["render", str(source), "--from", "5", "-o", str(video)]
    )
    assert result.exit_code == 1
    assert "error" in result.output
    assert not video.exists()


def test_to_at_or_before_from_is_an_error(tmp_path: Path) -> None:
    source = tmp_path / "window_still.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 16\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        self.wait(1)\n",
        encoding="utf-8",
    )
    video = tmp_path / "window.mp4"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["render", str(source), "--from", "0.5", "--to", "0.5", "-o", str(video)],
    )
    assert result.exit_code == 2
    assert not video.exists()


SOURCE_OF_FOUR_PLAYS = (
    "import manimgx as m\n"
    "m.config.pixel_width = m.config.pixel_height = 32\n"
    "m.config.frame_rate = 10\n"
    "class Only(m.Scene):\n"
    "    def construct(self):\n"
    "        square = m.Square(side_length=2, fill_opacity=1, fill_color=m.WHITE)\n"
    "        self.add(square)\n"
    "        self.add_subcaption('over the window', duration=2.5, offset=0.5)\n"
    "        for _ in range(4):\n"
    "            self.play(\n"
    "                square.animate.shift(1.5 * m.RIGHT), run_time=1, rate_func=m.linear\n"
    "            )\n"
)


def test_a_span_of_plays_is_the_window_their_times_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--plays 1-2` of four plays a second long each writes what `--from 1 --to 3`
    writes, frame for frame: both ends of a span of plays are included."""
    source = tmp_path / "window_plays.py"
    source.write_text(SOURCE_OF_FOUR_PLAYS, encoding="utf-8")
    timed, played = tmp_path / "timed.mp4", tmp_path / "played.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(
            source, output=timed, from_=1.0, to_=3.0, preset="ultrafast", crf=1
        )
        export.render(source, output=played, plays="1-2", preset="ultrafast", crf=1)
    finally:
        sys.modules.pop(source.stem, None)
    _assert_same_frames(_frames(timed), _frames(played))
    # the same window, so the same clock under its captions: a span of plays knows the
    # time of its first frame just as a span of time does
    assert played.with_suffix(".srt").read_text(encoding="utf-8") == timed.with_suffix(
        ".srt"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("span", "frames"),
    [
        ("0", 10),  # the first play alone
        ("2", 10),
        ("1-2", 20),
        ("2-", 21),  # to the scene's end, whose closing frame it keeps
        ("0-3", 41),
    ],
)
def test_a_span_of_plays_holds_just_those_plays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span: str, frames: int
) -> None:
    source = tmp_path / "window_plays.py"
    source.write_text(SOURCE_OF_FOUR_PLAYS, encoding="utf-8")
    video = tmp_path / "window.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(source, output=video, plays=span)
    finally:
        sys.modules.pop(source.stem, None)
    assert len(_frames(video)) == frames


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["--plays", "9"], 1),  # the scene has four
        (["--plays", "1-2", "--from", "1"], 2),
        (["--plays", "2-1"], 2),
        (["--plays", "two"], 2),
        (["--plays", ""], 2),
    ],
)
def test_a_span_of_plays_that_cannot_be_rendered_is_an_error(
    tmp_path: Path, arguments: list[str], code: int
) -> None:
    source = tmp_path / "window_plays.py"
    source.write_text(SOURCE_OF_FOUR_PLAYS, encoding="utf-8")
    video = tmp_path / "window.mp4"
    runner = CliRunner()
    result = runner.invoke(app, ["render", str(source), "-o", str(video), *arguments])
    assert result.exit_code == code, result.output
    assert not video.exists()


def test_a_span_of_plays_is_read_as_written() -> None:
    assert export.numbered("3-6") == (3, 6)
    assert export.numbered(" 3 ") == (3, 3)
    assert export.numbered("3-") == (3, None)


SOURCE_OF_PLAYS_OFF_THE_GRID = (
    "import manimgx as m\n"
    "m.config.pixel_width = m.config.pixel_height = 32\n"
    "m.config.frame_rate = 10\n"
    "class Only(m.Scene):\n"
    "    def construct(self):\n"
    "        square = m.Square(side_length=2, fill_opacity=1, fill_color=m.WHITE)\n"
    "        self.add(square)\n"
    "        square.add_updater(lambda mob, dt: mob.shift(2 * dt * m.RIGHT))\n"
    "        self.wait(0.55)\n"  # play 0: ends between two frames
    "        self.wait(0.05)\n"  # play 1: no frame falls in it at all
    "        self.wait(1)\n"  # play 2: begins between two frames
)


@pytest.mark.parametrize(("span", "from_", "to_"), [("0", 0.0, 0.55), ("2", 0.6, None)])
def test_a_span_of_plays_whose_ends_fall_between_frames_is_their_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    span: str,
    from_: float,
    to_: float | None,
) -> None:
    """A play need not begin or end on a frame. The frames of a span of plays are still
    the frames of the time it covers, so `--plays` and `--from`/`--to` agree."""
    source = tmp_path / "window_grid.py"
    source.write_text(SOURCE_OF_PLAYS_OFF_THE_GRID, encoding="utf-8")
    timed, played = tmp_path / "timed.mp4", tmp_path / "played.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(
            source, output=timed, from_=from_, to_=to_, preset="ultrafast", crf=1
        )
        export.render(source, output=played, plays=span, preset="ultrafast", crf=1)
    finally:
        sys.modules.pop(source.stem, None)
    _assert_same_frames(_frames(timed), _frames(played))


def test_a_play_with_no_frame_of_its_own_is_an_error(tmp_path: Path) -> None:
    """A play that begins and ends between two frames has nothing to write: say so,
    rather than leave a video with no frames in it."""
    source = tmp_path / "window_grid.py"
    source.write_text(SOURCE_OF_PLAYS_OFF_THE_GRID, encoding="utf-8")
    video = tmp_path / "window.mp4"
    runner = CliRunner()
    result = runner.invoke(
        app, ["render", str(source), "-o", str(video), "--plays", "1"]
    )
    assert result.exit_code == 1
    assert "no frame of its own" in result.output
    assert not video.exists()


def _tone(seconds: float, hertz: float) -> "m.Sound":
    """A tone, as samples at the mixer's own rate: never silent, so a cut shows."""
    t = np.arange(round(seconds * RATE)) / RATE
    return m.Sound((0.3 * np.sin(m.TAU * hertz * t)).astype(np.float32), rate=RATE)


@pytest.mark.config(pixel_width=16, pixel_height=16, frame_rate=10)
def test_a_windows_sound_is_the_whole_films_cut_to_the_window(tmp_path: Path) -> None:
    """The window hears what the film has there: a sound that began before it is heard
    from its middle, one that ended before it is not heard at all, and every sample is the
    full film's, but for the fade the cut itself needs."""

    class Sounded(m.Scene):
        def construct(self) -> None:
            self.add_sound(_tone(0.4, 300))  # over before the window
            self.wait(0.5)
            self.add_sound(_tone(1.1, 440))  # begins before it, plays into it
            self.wait(0.7)
            self.add_sound(_tone(0.3, 660))  # begins inside it
            self.wait(1.3)

    whole = Sounded()
    whole.render()  # no video: the film counts its frames and mixes its sound all the same
    full = whole.film.soundtrack()
    assert full is not None
    made = export.windowed(
        Sounded,
        Format(16, 16, 10),
        tmp_path / "window.mp4",
        10,
        20,
        None,
        "ultrafast",
        1.0,
    )
    window = made.film.soundtrack()
    assert window is not None
    want = full[RATE : 2 * RATE].copy()
    _ramp(want, CUT, 0.0)
    assert np.array_equal(window, want)
    heard = round(CUT * RATE)  # past the fade, the 440 Hz tone is already playing
    assert np.abs(window[heard : heard + 100]).max() > 0.1


@pytest.mark.config(pixel_width=16, pixel_height=16, frame_rate=10)
def test_a_window_from_the_scenes_start_fades_nothing_in(tmp_path: Path) -> None:
    """Nothing is cut where a window begins at the scene's own start, so its sound is the
    film's own from the first sample; its end, which does cut a sound, fades."""

    class Sounded(m.Scene):
        def construct(self) -> None:
            self.add_sound(_tone(1.5, 440))
            self.wait(2)

    whole = Sounded()
    whole.render()
    full = whole.film.soundtrack()
    assert full is not None
    made = export.windowed(
        Sounded,
        Format(16, 16, 10),
        tmp_path / "window.mp4",
        0,
        10,
        None,
        "ultrafast",
        1.0,
    )
    window = made.film.soundtrack()
    assert window is not None
    cut = round(CUT * RATE)
    assert np.array_equal(window[: RATE - cut], full[: RATE - cut])
    tail = np.abs(window[RATE - cut :]).mean()
    assert tail < np.abs(full[RATE - cut : RATE]).mean() / 2


@pytest.mark.config(pixel_width=16, pixel_height=16, frame_rate=10)
def test_a_window_with_no_sound_in_the_whole_scene_has_none(tmp_path: Path) -> None:
    class Silent(m.Scene):
        def construct(self) -> None:
            self.wait(2)

    made = export.windowed(
        Silent,
        Format(16, 16, 10),
        tmp_path / "window.mp4",
        10,
        15,
        None,
        "ultrafast",
        1.0,
    )
    assert made.film.soundtrack() is None
    with av.open(str(tmp_path / "window.mp4")) as container:
        assert not container.streams.audio


def test_a_windows_video_carries_its_sound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MP4 a window writes has an audio stream as long as its frames."""
    source = tmp_path / "window_hum.py"
    source.write_text(
        "import numpy as np\n"
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 16\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        self.wait(0.5)\n"
        "        t = np.arange(48000) / 48000\n"
        "        self.add_sound(m.Sound(np.sin(m.TAU * 440 * t).astype(np.float32), rate=48000))\n"
        "        self.wait(1.5)\n",
        encoding="utf-8",
    )
    video = tmp_path / "window.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(source, output=video, from_=0.8, to_=1.3)
    finally:
        sys.modules.pop(source.stem, None)
    with av.open(str(video)) as container:
        audio = container.streams.audio
        assert len(audio) == 1
        assert audio[0].duration is not None
        seconds = float(audio[0].duration * audio[0].time_base)
    assert seconds == pytest.approx(0.5, abs=0.05)


def test_a_window_writes_the_subtitles_it_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`render` writes a window's captions beside it, timed from the window's own start:
    one that began before the window starts at zero."""
    source = tmp_path / "window_said.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 16\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        self.wait(0.6)\n"
        "        self.add_subcaption('straddles', duration=1.0)\n"
        "        self.wait(1.4)\n",
        encoding="utf-8",
    )
    video = tmp_path / "window.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(source, output=video, from_=1.0, to_=2.0)
    finally:
        sys.modules.pop(source.stem, None)
    srt = video.with_suffix(".srt").read_text(encoding="utf-8")
    assert "straddles" in srt
    assert "00:00:00,000 --> 00:00:00,600" in srt


@pytest.mark.config(pixel_width=16, pixel_height=16, frame_rate=10)
def test_a_windows_captions_are_the_ones_it_shows_timed_from_its_start(
    tmp_path: Path,
) -> None:
    """A caption gone before the window is not in it, one that straddles its start is
    clipped to it, and the rest are the scene's, moved back to the window's own clock."""

    class Captioned(m.Scene):
        def construct(self) -> None:
            self.add_subcaption("gone", duration=0.4)
            self.wait(0.6)
            self.add_subcaption("straddles", duration=1.0)  # 0.6 to 1.6 s
            self.wait(0.8)
            self.add_subcaption("inside", duration=0.3)  # 1.4 to 1.7 s
            self.wait(1.2)

    made = export.windowed(
        Captioned,
        Format(16, 16, 10),
        tmp_path / "window.mp4",
        10,
        20,
        None,
        "ultrafast",
        1.0,
    )
    shown = [(c.text, round(c.start, 6), round(c.end, 6)) for c in made.film.captions()]
    assert shown == [("straddles", 0.0, 0.6), ("inside", 0.4, 0.7)]


def test_a_window_respects_resolution_and_fps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """-r and --fps set the look a window is rendered at, and the frames --from and --to
    name: the file's own config (32x18 at 10 fps) must not leak through."""
    source = tmp_path / "window_look.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 32\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        square = m.Square()\n"
        "        self.add(square)\n"
        "        self.play(square.animate.shift(2 * m.RIGHT), run_time=1, rate_func=m.linear)\n",
        encoding="utf-8",
    )
    video = tmp_path / "window.mp4"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(source),
            "-o",
            str(video),
            "-r",
            "16x16",
            "--fps",
            "20",
            "--from",
            "0.25",
            "--to",
            "0.5",
        ],
    )
    assert result.exit_code == 0, result.output
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        assert (stream.codec_context.width, stream.codec_context.height) == (16, 16)
        assert round(float(stream.average_rate)) == 20
    assert len(_frames(video)) == 5  # 0.25..0.5 s at 20 fps: frames 5 up to 10


def test_a_window_shows_the_same_pure_tween_frames_as_a_full_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One play entirely before the window (skipped by `_advance_tweens`, not just
    uncomputed by `_emit`), then a window that opens exactly where it ends and closes in
    the middle of the next play (forcing the general path there)."""
    source = tmp_path / "window_pure.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 32\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        square = m.Square(side_length=4, fill_opacity=1, fill_color=m.WHITE)\n"
        "        self.play(m.FadeIn(square), run_time=1, rate_func=m.linear)\n"
        "        self.play(square.animate.shift(2 * m.RIGHT), run_time=1, rate_func=m.linear)\n"
        "        self.play(m.FadeOut(square), run_time=1, rate_func=m.linear)\n",
        encoding="utf-8",
    )
    full, window = tmp_path / "full.mp4", tmp_path / "window.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(source, output=full, preset="ultrafast", crf=1)
        export.render(
            source, output=window, from_=1.0, to_=2.5, preset="ultrafast", crf=1
        )
    finally:
        sys.modules.pop(source.stem, None)
    _assert_same_frames(_frames(full)[10:25], _frames(window))


def test_a_window_shows_the_same_updater_frames_as_a_full_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An updater forces the general path throughout, so this exercises `_emit`'s own
    pre-window skip across a play boundary, not `_advance_tweens`."""
    source = tmp_path / "window_updater.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = m.config.pixel_height = 32\n"
        "m.config.frame_rate = 10\n"
        "class Only(m.Scene):\n"
        "    def construct(self):\n"
        "        dot = m.Dot(radius=0.8, color=m.WHITE)\n"
        "        dot.add_updater(lambda mob, dt: mob.shift(2 * dt * m.RIGHT))\n"
        "        self.add(dot)\n"
        "        self.wait(1)\n"
        "        self.play(m.FadeOut(dot), run_time=1, rate_func=m.linear)\n",
        encoding="utf-8",
    )
    full, window = tmp_path / "full.mp4", tmp_path / "window.mp4"
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        export.render(source, output=full, preset="ultrafast", crf=1)
        export.render(
            source, output=window, from_=0.5, to_=1.5, preset="ultrafast", crf=1
        )
    finally:
        sys.modules.pop(source.stem, None)
    _assert_same_frames(_frames(full)[5:15], _frames(window))
