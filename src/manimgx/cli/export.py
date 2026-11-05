"""Offline scene exports: video, inspections and presentations."""

import json
import os
import re
import time
import webbrowser
from dataclasses import replace
from fractions import Fraction
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import quote

import typer
from PIL import Image
from rich.console import Console

from manimgx.animation import clock
from manimgx.animation.timeline import Animation
from manimgx.cli.diagnostics import Names, names, written_frame
from manimgx.cli.scenes import (
    File,
    Format,
    Fps,
    Resolution,
    SceneName,
    fail,
    report_error,
    scene,
    take,
)
from manimgx.cli.storyboard import Sheets, Watch, line
from manimgx.rendering.film import (
    DEFAULT_ENCODER_CRF,
    DEFAULT_ENCODER_PRESET,
    Caption,
    Cut,
    Film,
    Frame,
    Play,
    X264Preset,
)
from manimgx.scene import Scene
from manimgx.settings import config

if TYPE_CHECKING:
    import numpy as np

    from manimgx.animation.transform import Transform
    from manimgx.drawing.geometry import Path as MotionPath


def render(
    file: File,
    name: SceneName = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="The video (.mp4). [default: <Scene>.mp4 beside the file]",
        ),
    ] = None,
    resolution: Resolution = None,
    fps: Fps = None,
    from_: Annotated[
        float | None,
        typer.Option(
            "--from",
            min=0,
            show_default=False,
            help="Only from this time, in seconds. [default: the start]",
        ),
    ] = None,
    to_: Annotated[
        float | None,
        typer.Option(
            "--to",
            min=0,
            show_default=False,
            help="Only up to (not including) this time, in seconds. [default: the end]",
        ),
    ] = None,
    plays: Annotated[
        str | None,
        typer.Option(
            "--plays",
            show_default=False,
            metavar="A[-B]",
            help="Only these plays, as the storyboard numbers them, both ends included:"
            " '3-6', '3' alone, or '3-' to the end. Not with --from or --to.",
        ),
    ] = None,
    preset: Annotated[
        X264Preset,
        typer.Option(
            help="Encoding speed: faster presets encode sooner but produce larger files."
        ),
    ] = DEFAULT_ENCODER_PRESET,
    crf: Annotated[
        float,
        typer.Option(
            min=0,
            max=51,
            help="Video quality: lower values give higher quality and larger files.",
        ),
    ] = DEFAULT_ENCODER_CRF,
) -> None:
    """Render a scene to an MP4 video, with its sound.

    Also writes a storyboard beside the video (the frame at each play's end, layout problems
    outlined and numbered) and lists those problems — see `manimgx inspect` — and, if the
    scene speaks or has subcaptions, its subtitles (.srt).

    With --from or --to, writes only that window of time; with --plays, the plays it names,
    both ends included, as the storyboard numbers them. The scene runs from its start, since
    what the window shows depends on what came before, but stops at the window's end, so
    nothing after it runs either. It sounds and reads as the whole film does there — a sound still playing at --from
    is heard from its middle, and the captions are the ones the window shows — but it has no
    storyboard. Its first section is the one the scene is in at --from, and a section begun
    inside it begins one of the video too; the sections before the window are not in it."""
    kind = scene(file, name)
    video = output or file.with_name(f"{kind.__name__}.mp4")
    if video.suffix.lower() != ".mp4":
        raise fail(f"error: {video}: ManimGX writes MP4 video; name the output *.mp4")
    look = Format.own(resolution, fps)
    if plays is not None and (from_ is not None or to_ is not None):
        raise fail("error: --plays names a window of its own; not with --from or --to")
    if plays is not None or from_ is not None or to_ is not None:
        fps_exact = clock.rational(look.fps)
        start = clock.frame_at(from_ or 0.0, fps_exact)
        end = None if to_ is None else clock.frame_at(to_, fps_exact)
        if end is not None and end <= start:
            raise fail("error: --to must be after --from")
        span = None if plays is None else numbered(plays)
        started = time.perf_counter()
        made = windowed(kind, look, video, start, end, span, preset, crf)
        took = time.perf_counter() - started
        megabytes = video.stat().st_size / 1e6
        typer.echo(
            f"{video}  {look}, {megabytes:.1f} MB (rendered in {took:.1f} s):"
            " no storyboard"
        )
        if subtitles := made.film.subtitles():
            srt = video.with_suffix(".srt")
            srt.write_text(subtitles, encoding="utf-8")
            typer.echo(f"subtitles: {srt}")
        return
    watch = Watch(Sheets(video.with_name(f"{video.stem}.storyboard.png")))
    started = time.perf_counter()
    try:
        made, _ = take(kind, look, video=video, plays=watch, preset=preset, crf=crf)
    finally:
        sheets = watch.storyboard.close()
    took = time.perf_counter() - started
    megabytes = video.stat().st_size / 1e6
    typer.echo(
        f"{video}  {float(made.clock):.2f} s, {look}, {megabytes:.1f} MB "
        f"(rendered in {took:.1f} s)"
    )
    typer.echo(f"storyboard: {', '.join(str(s) for s in sheets)}")
    subtitles = made.film.subtitles()
    if subtitles:
        srt = video.with_suffix(".srt")
        srt.write_text(subtitles, encoding="utf-8")
        typer.echo(f"subtitles: {srt}")
    typer.echo(watch.report(timeline=False, film=made.film))


class WindowFilm(Film):
    """A window's film: it hears and captions what the whole film has between `since`, the
    scene time its first frame shows, and its own end.

    Its clips are the scene's, timed from the scene's start, as the window's picture is the
    scene's picture there. Its sound is the film's own soundtrack, mixed over the whole
    timeline and cut to the window, so overlaps, loops, ducking and the fades of a sound cut
    short are what a full render gives; only the cut itself is new, and it is ramped so that
    a wave sliced through the middle does not click.
    """

    def __init__(
        self,
        video: str | os.PathLike[str],
        since: Fraction,
        *,
        preset: X264Preset = DEFAULT_ENCODER_PRESET,
        crf: float = DEFAULT_ENCODER_CRF,
    ) -> None:
        """
        Args:
            video: The MP4 file the window is encoded into.
            since: The scene time its first frame shows.
            preset: The x264 preset it is encoded with.
            crf: Its quality, as x264's constant rate factor.
        """
        super().__init__(video, preset=preset, crf=crf)
        self.since = since
        """The scene time this film's first frame shows."""

    def soundtrack(self) -> "np.ndarray | None":
        """The whole film's sound over the window: its clips mixed from the scene's start
        and cut to the window, its head faded in over [`CUT`][manimgx.audio.sound.CUT] so
        that a wave cut through the middle does not click. A sound still playing at the
        window's end fades out there, as one the film's own end cuts short does."""
        # the mixer's own ramp: the cut fades as a sound cut short does
        from manimgx.audio.sound import CUT, RATE, _ramp, mix

        whole = mix(self.clips, self.since + self.frame_count / self.fps)
        if whole is None:
            return None
        sound = whole[round(self.since * RATE) :].copy()
        # its end needs no fade: the mix fades a sound its own end cuts short
        _ramp(sound, CUT if self.since else 0.0, 0.0)
        return sound

    def captions(self) -> list[Caption]:
        """The whole film's captions over the window, timed from its first frame: those it
        shows, each clipped to it."""
        since, length = float(self.since), float(self.frame_count / self.fps)
        shown = []
        for caption in super().captions():
            start, end = caption.start - since, caption.end - since
            if end > 0 and start < length:
                shown.append(
                    replace(caption, start=max(start, 0.0), end=min(end, length))
                )
        return shown


def windowed(
    kind: type[Scene],
    look: Format,
    video: Path,
    start: int,
    end: int | None,
    span: tuple[int, int | None] | None,
    preset: X264Preset,
    crf: float,
) -> Scene:
    """Run `kind` at `look`, writing `video` only for the window: frames `start` up to (not
    including) `end`, or, with a `span`, the plays it names, both included.

    The scene runs from its start, as what a frame in the window shows depends on what came
    before it, but stops at the window's end: nothing after it runs. Only the window is drawn
    and encoded; its sound and captions are the whole film's over the window (see
    `WindowFilm`).

    Args:
        kind: The scene.
        look: The size and frame rate it is rendered at.
        video: The MP4 the window is written to.
        start: Its first frame, when it is a span of time.
        end: One past its last frame, when it is a span of time; None, the scene's end.
        span: The first and last play it holds, both included (None as the last: to the
            scene's end); None, the window is the span of time instead.
        preset: The x264 preset it is encoded with.
        crf: Its quality, as x264's constant rate factor.

    Returns:
        The scene, run.
    """
    config.pixel_width, config.pixel_height = look.width, look.height
    config.frame_rate = look.fps
    fps_exact = clock.rational(look.fps)
    opened = False
    empty = False  # the span's plays all fell between two frames

    class Windowed(Scene):
        """Run frame by frame, or at once between its own keyframes, through `kind`'s own
        evaluation methods; only the window is drawn and encoded."""

        def _open(self) -> None:
            nonlocal opened
            held = self.film.sections[-1]  # the section in force where the window opens
            # the sounds and captions placed so far: both timed from the scene's start
            clips, said = self.film.clips, self.film.subcaptions
            since = Fraction(self.frame) / fps_exact  # this first frame's time
            self.film = WindowFilm(os.fspath(video), since, preset=preset, crf=crf)
            self.film.sections[0] = replace(held, frame=0)
            self.film.clips[:] = clips
            self.film.subcaptions[:] = said
            opened = True

        def _boundary(self) -> None:
            """Open the window at its first frame, and cut the film past its last.

            The play being run is `num_plays - 1`: the scene counts a play as it begins
            it. A span of plays needs no frame of its own, as a play begins and ends
            between two frames: the window's edges fall where `_emit` is entered, never
            inside it.
            """
            if not opened:
                begun = self.num_plays > span[0] if span else self.frame >= start
                if begun:
                    self._open()
            if opened:
                over = (
                    span[1] is not None and self.num_plays - 1 > span[1]
                    if span
                    else end is not None and self.frame >= end
                )
                if over:
                    nonlocal empty
                    empty = not self.film.frame_count
                    raise Cut

        def _pure_tweens(
            self, anim: Animation, alpha: list[float]
        ) -> "tuple[list[tuple[Transform, MotionPath]], set[int]] | None":
            self._boundary()
            if span is not None:
                return super()._pure_tweens(anim, alpha)  # its edges are plays' own
            lo, hi = self.frame, self.frame + len(alpha)
            if lo < start < hi or (end is not None and lo < end < hi):
                return None  # the window splits this play: every frame computed
            return super()._pure_tweens(anim, alpha)

        def _advance_tweens(
            self,
            anim: Animation,
            tweens: "list[tuple[Transform, MotionPath]]",
            alpha: list[float],
            introduced: set[int],
        ) -> None:
            if opened:
                super()._advance_tweens(anim, tweens, alpha, introduced)
            else:  # before the window: its frames are never drawn, so never made
                self.frame += len(alpha)

        def _emit(self, repeat: int = 1) -> None:
            while repeat > 0:
                self._boundary()
                if opened:
                    chunk = (
                        repeat
                        if span is not None or end is None
                        else min(repeat, end - self.frame)
                    )
                    super()._emit(chunk)
                else:  # before the window: its frames are never drawn, so never made
                    chunk = (
                        repeat if span is not None else min(repeat, start - self.frame)
                    )
                    self.frame += chunk
                repeat -= chunk

    combined = type(kind.__name__, (kind, Windowed), {"__module__": kind.__module__})
    shown = Console(stderr=True)
    try:
        with shown.status(f"{kind.__name__}…", spinner="dots"):
            made = combined()
            made.render()
    except Exception as error:
        raise fail(report_error(error), 1) from None
    if empty and span is not None:
        video.unlink(missing_ok=True)
        raise fail(
            f"error: play {span[0]} has no frame of its own: it begins and ends between"
            " two frames",
            1,
        )
    if not opened:
        if span is not None:
            raise fail(
                f"error: the scene has {made.num_plays} plays, numbered 0 to"
                f" {made.num_plays - 1}; --plays is past its end",
                1,
            )
        raise fail(
            f"error: the scene ends at {float(made.clock):.2f} s; --from is past it", 1
        )
    return made


def numbered(given: str) -> tuple[int, int | None]:
    """The first and last play `--plays` names, both included; None as the last means the
    scene's end. `3-6` is 3 to 6, `3` is play 3 alone, and `3-` is 3 to the end."""
    first, dash, last = given.strip().partition("-")
    try:
        a = int(first)
        b = None if dash and not last else int(last or first)
    except ValueError:
        raise fail(
            f"error: {given!r} is not a span of plays: 'A', 'A-B' or 'A-'"
        ) from None
    if a < 0 or (b is not None and b < a):
        raise fail(
            "error: --plays counts from 0, and its last play is not before its first"
        )
    return a, b


def moments(given: list[str]) -> set[Fraction | None]:
    """Distinct times in seconds; None means `end`. `-t 1,2` is `-t 1 -t 2`."""
    out: set[Fraction | None] = set()
    for part in (p.strip() for text in given for p in text.split(",")):
        if not part:
            continue
        try:
            moment = None if part == "end" else Fraction(part)
            if moment is not None and moment < 0:
                raise ValueError
        except (ValueError, ZeroDivisionError):
            raise fail(
                f"error: {part!r} is not a time: non-negative seconds or 'end'"
            ) from None
        out.add(moment)
    if given and not out:
        raise fail("error: --time needs seconds from the start, or 'end'")
    return out


def inspect(
    file: File,
    name: SceneName = None,
    time: Annotated[
        list[str] | None,
        typer.Option(
            "--time",
            "-t",
            metavar="TIME",
            help=(
                "Seconds from the start, or 'end'; several: repeat -t or separate with"
                " commas."
            ),
            show_default=False,
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="The storyboard (.png). [default: <Scene>.storyboard.png beside the file]",
        ),
    ] = None,
) -> None:
    """Inspect a scene: annotated PNGs, timeline and 2D layout checks, without video.

    Samples play and wait endings by default. With -t, inspects the frames a video player
    shows at those times; 'end' is the last frame. Checks for clipped content, overlapping
    text, lines or fills over text, and small labels. 3D scenes get pictures and a timeline;
    layout checks are skipped. Only sampled moments are checked.

    Pictures are chronological, captioned #play t=… file:line, with problems outlined and
    numbered. Six fit on each sheet (more go on `<name>-2.png`, …). Default sampling omits
    consecutive identical pictures. With -t, only the requested frames are drawn, and the
    scene stops after the last requested frame's play unless 'end' is included.

    Exits 1 for layout problems; notes, such as a graph leaving the frame, do not count.
    """
    kind = scene(file, name)
    wanted = moments(time or [])
    target = output or file.with_name(f"{kind.__name__}.storyboard.png")
    if target.suffix.lower() != ".png":
        raise fail(
            f"error: {target}: a storyboard is a PNG image; name the output *.png"
        )
    look = Format.own()
    fps = clock.rational(look.fps)
    # The last sample no later than the requested observed instant.
    pending = sorted(
        ((clock.frame_at(t, fps, after=True) - 1, t) for t in wanted if t is not None),
        reverse=True,
    )
    known: Names | None = None
    watch = Watch(Sheets(target))

    class Sampling(Scene):
        """Observe selected frames through the scene's existing evaluation methods."""

        def _emit(self, repeat: int = 1) -> None:
            while pending and pending[-1][0] < self.frame + repeat:
                when = Fraction(pending.pop()[0]) / fps
                watch.see(self, when, known=known)
            super()._emit(repeat)

        def _pure_tweens(
            self, anim: Animation, alpha: list[float]
        ) -> "tuple[list[tuple[Transform, MotionPath]], set[int]] | None":
            if pending and pending[-1][0] < self.frame + len(alpha):
                return None  # this play needs its mutable world at the selected frames
            return super()._pure_tweens(anim, alpha)

    def ended(made: Scene, play: Play, animations: tuple[Animation, ...]) -> None:
        nonlocal known
        if not made.three_d:
            known = names(made, written_frame())
        watch.lines.append(line(play, animations))
        if None not in wanted and not pending:
            raise Cut  # the play showing the last frame asked for is over

    try:
        # Only an inspection with selected frames uses the adapter. Scene and render
        # keep their ordinary evaluation path, including subclasses' overrides.
        observed = (
            type(kind.__name__, (kind, Sampling), {"__module__": kind.__module__})
            if pending
            else kind
        )
        made, film = take(observed, look, plays=ended if wanted else watch)
        if pending:
            raise fail(
                f"error: the scene ends at {float(made.clock):.2f} s; there is no frame at"
                f" {pending[-1][1]} s",
                1,
            )
        if None in wanted or (not wanted and not film.plays):
            watch.see(made, Fraction(film.frame_count - 1) / fps, known=known)
    finally:
        sheets = watch.storyboard.close()
    typer.echo(
        f"{file}: {kind.__name__}, {float(made.clock):.2f} s, {len(film.plays)} plays"
    )
    typer.echo(f"storyboard: {', '.join(str(s) for s in sheets)}")
    typer.echo(watch.report(film=film if not wanted or None in wanted else None))
    if watch.layout.numbers:
        raise typer.Exit(1)


def present(
    file: File,
    name: SceneName = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="The video (.mp4); the page is written beside it (.html). [default:"
            " <Scene>.mp4 beside the file]",
        ),
    ] = None,
    resolution: Resolution = None,
    fps: Fps = None,
    pdf: Annotated[
        bool,
        typer.Option(
            help="Also write a PDF: the picture each slide ends on, a page each."
        ),
    ] = False,
    show: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the page in the browser.")
    ] = True,
) -> None:
    """Present a scene: its sections are the slides.

    Renders the video, writes a page that plays it (it stops at the end of each section,
    until you go on), and opens it. Keys: → or Space next, ← back, F full screen, B black,
    Shift+P presenter view (notes, the next slide, a timer), C captions, ? help. A clicker
    works: it sends the same keys. Begin a section with `self.next_section(...)` in the scene.
    """
    kind = scene(file, name)
    video = output or file.with_name(f"{kind.__name__}.mp4")
    if video.suffix.lower() != ".mp4":
        raise fail(f"error: {video}: ManimGX writes MP4 video; name the output *.mp4")
    look = Format.own(resolution, fps)
    pictures: list[bytes] = []  # the pictures slides end on, for the PDF
    last: list[Frame] = []

    def keep(frame: Frame) -> None:
        if frame.key and frame.index > 0:
            pictures.append(frame.pixels())
        last[:] = [frame]

    started = time.perf_counter()
    made, film = take(kind, look, video=video, frames=keep if pdf else None)
    if pdf and last:
        pictures.append(last[0].pixels())  # the film's last picture ends the last slide
    html = video.with_suffix(".html")
    html.write_text(page(film, Path(video.name), kind.__name__), encoding="utf-8")
    slides = len(film.sections)
    typer.echo(
        f"{video}  {float(made.clock):.2f} s, {look}, {slides} slides (rendered in"
        f" {time.perf_counter() - started:.1f} s)"
    )
    typer.echo(f"{html}")
    if pdf:
        size = (config.pixel_width, config.pixel_height)
        images = [Image.frombytes("RGBA", size, p).convert("RGB") for p in pictures]
        handout = video.with_suffix(".pdf")
        images[0].save(handout, save_all=True, append_images=images[1:])
        typer.echo(f"{handout}")
    if show:
        webbrowser.open(html.resolve().as_uri())


def page(film: Film, video: str | os.PathLike[str], title: str = "ManimGX") -> str:
    """The page that presents `film`, whose video is `video` (a path or URL, as the page
    will find it: relative to the page, typically).

    Args:
        film: The film, rendered.
        video: Where the page finds its video: a URL string, or a filesystem path
            (relative to the page, unless absolute).
        title: The page's title.

    Returns:
        The page's HTML.
    """
    deck = {
        "fps": float(film.fps),
        "frames": film.frame_count,
        "sections": [
            {"name": s.name, "frame": s.frame, "type": s.type, "notes": s.notes}
            for s in film.sections
        ],
        "captions": [[c.start, c.end, c.text] for c in film.captions()],
    }
    html = (files("manimgx") / "cli" / "present.html").read_text(encoding="utf-8")
    if not isinstance(video, str):
        path = Path(video)
        video = path.as_uri() if path.is_absolute() else quote(path.as_posix())
    values = {
        "DECK_TITLE": escape(title),
        "DECK_VIDEO": escape(video),
        "DECK_JSON": json.dumps(deck).replace("</", "<\\/"),
    }
    return re.sub(r"DECK_(?:TITLE|VIDEO|JSON)", lambda match: values[match[0]], html)
