"""Offline scene exports: video, stills, checks and presentations."""

import json
import math
import os
import time
import webbrowser
from fractions import Fraction
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer
from PIL import Image

from manimgx.animation.timeline import Animation
from manimgx.cli.scenes import (
    File,
    Format,
    Fps,
    Resolution,
    SceneName,
    fail,
    scene,
    take,
)
from manimgx.cli.storyboard import PER_SHEET, Sheets, Watch, caption, tile
from manimgx.config import config
from manimgx.rendering.film import Cut, Film, Frame, Play, X264Preset
from manimgx.scene import Scene


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
    preset: Annotated[
        X264Preset,
        typer.Option(
            help="x264 encoding preset; faster presets render faster while making larger files."
        ),
    ] = "ultrafast",
    crf: Annotated[
        float, typer.Option(min=0, max=51, help="x264 CRF (0 to 51); lower is better.")
    ] = 18.0,
) -> None:
    """Render a scene to an MP4 video, with its sound.

    Also writes a storyboard beside the video (the frame at each play's end, layout problems
    outlined and numbered) and lists those problems — see `manimgx check` — and, if the
    scene speaks or has subcaptions, its subtitles (.srt)."""
    kind = scene(file, name)
    video = output or file.with_name(f"{kind.__name__}.mp4")
    if video.suffix.lower() != ".mp4":
        raise fail(f"error: {video}: manimgx writes MP4 video; name the output *.mp4")
    look = Format.own(resolution, fps)
    watch = Watch(Sheets(video.with_name(f"{video.stem}.storyboard.png")))
    started = time.perf_counter()
    made, _ = take(kind, look, video=video, plays=watch, preset=preset, crf=crf)
    sheets = watch.close()
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


def check(
    file: File,
    name: SceneName = None,
    storyboard: Annotated[
        Path | None,
        typer.Option(
            "--storyboard",
            "-s",
            help=(
                "The storyboard (.png). [default: <Scene>.storyboard.png beside the"
                " file]"
            ),
        ),
    ] = None,
) -> None:
    """Check a scene: timeline, storyboard, layout.

    Runs the scene without video. Prints its timeline (each play: when, the line of code,
    what it played) and the layout problems a viewer would see when each play ends: anything
    the frame cuts off, texts that overlap, lines through or touching a text, fills over a
    text, text too small to read. Writes a storyboard: the frame at each play's end, problems
    outlined and numbered. Exits 1 if there are problems (notes, such as a graph leaving the
    frame, do not count)."""
    kind = scene(file, name)
    watch = Watch(
        Sheets(storyboard or file.with_name(f"{kind.__name__}.storyboard.png"))
    )
    # the take a render makes (its frames computed, none drawn): a scene whose updaters count
    # frames is the same world here as in its video
    made, film = take(kind, Format.own(), plays=watch)
    sheets = watch.close()
    typer.echo(
        f"{file}: {kind.__name__}, {float(made.clock):.2f} s, {len(film.plays)} plays"
    )
    typer.echo(f"storyboard: {', '.join(str(s) for s in sheets)}")
    typer.echo(watch.report(film=film))
    if watch.problems():
        raise typer.Exit(1)


END = "end"


def moments(given: list[str]) -> list[str]:
    """The times asked for, in order, once each: seconds or `end`; `-t 1,2` is `-t 1 -t 2`."""
    out: list[str] = []
    for part in (p.strip() for text in given for p in text.split(",")):
        if not part:
            continue
        if part != END:
            try:
                seconds = float(part)
            except ValueError:
                raise fail(
                    f"error: {part!r} is not a time: seconds (e.g. 2.5) or 'end'"
                ) from None
            if not math.isfinite(seconds) or seconds < 0:
                raise fail(
                    f"error: {part!r} is not a time: seconds from the start, or 'end'"
                )
            part = f"{seconds:g}"
        if part not in out:
            out.append(part)
    return out or [END]


def on_screen(plays: list[Play], time: Fraction) -> Play | None:
    """The play whose frames show `time`: the last to begin by then (after the last play: it,
    as it left the world)."""
    shown = None
    for play in plays:
        if play.start <= time:
            shown = play
    return shown


def still(
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
            show_default="end",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="The sheet (.png). [default: <Scene>.png beside the file]",
        ),
    ] = None,
) -> None:
    """Draw the frames on screen at given times, on one sheet (PNG).

    The frame at t seconds is the one on screen then (what a video player shows at t); `end` is
    the scene's last frame. Each is captioned `#play t=… file:line`: the play on screen and the
    line of code that played it. Six to a sheet (more go on `<name>-2.png`, …). Only the
    frames asked for are drawn, and the scene runs no further than the play showing the last.
    """
    kind = scene(file, name)
    wanted = moments(time or [])
    target = output or file.with_name(f"{kind.__name__}.png")
    if target.suffix.lower() != ".png":
        raise fail(f"error: {target}: a still is a PNG image; name the output *.png")
    look = (
        Format.own()
    )  # the frames the video shows (drawn at its size, reduced to tiles)
    fps = Fraction(look.fps).limit_denominator(1000)
    # the frame on screen at t shows time ⌊t·fps⌋ / fps
    at = {m: math.floor(float(m) * look.fps + 1e-9) for m in wanted if m != END}
    through = Fraction(max(at.values(), default=0)) / fps
    drawn: dict[int, Image.Image] = {}
    last: list[Frame] = []

    def keep(frame: Frame) -> None:
        span = range(frame.index, frame.index + frame.repeat)
        if hits := [k for k in at.values() if k in span and k not in drawn]:
            picture = tile(frame.pixels(), look.width, look.height)
            drawn.update(dict.fromkeys(hits, picture))
        last[:] = [frame]

    def enough(_: Scene, play: Play, __: tuple[Animation, ...]) -> None:
        if END not in wanted and play.end > through:
            raise Cut  # the play showing the last frame asked for is over

    made, film = take(kind, look, frames=keep, plays=enough)
    if END in wanted and last:  # the film's last frame: nothing was sent after it
        drawn[-1] = tile(last[0].pixels(), look.width, look.height)
    frames = {m: -1 if m == END else at[m] for m in wanted}
    if missing := [m for m, k in frames.items() if k not in drawn]:
        raise fail(
            f"error: the scene ends at {float(made.clock):.2f} s; there is no frame at"
            f" {missing[0]} s",
            1,
        )
    sheets = Sheets(target)
    captions: list[str] = []
    for moment, k in frames.items():
        shown = made.clock if k == -1 else Fraction(k) / fps
        when = f"{float(made.clock):.2f}s (end)" if k == -1 else f"{moment}s"
        captions.append(caption(on_screen(film.plays, shown), when))
        sheets.add(captions[-1], drawn[k])
    for n, sheet in enumerate(sheets.close()):  # each sheet, and what is on it
        typer.echo(
            f"{sheet}  {'; '.join(captions[n * PER_SHEET : (n + 1) * PER_SHEET])}"
        )


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
        raise fail(f"error: {video}: manimgx writes MP4 video; name the output *.mp4")
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
    html.write_text(page(film, video.name, kind.__name__), encoding="utf-8")
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


def page(film: Film, video: str | os.PathLike[str], title: str = "manimgx") -> str:
    """The page that presents `film`, whose video is `video` (a path or URL, as the page
    will find it: relative to the page, typically).

    Args:
        film: The film, rendered.
        video: Where the page finds its video.
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
    return (
        html.replace("DECK_TITLE", title)
        .replace("DECK_VIDEO", Path(video).as_posix())
        .replace("DECK_JSON", json.dumps(deck).replace("</", "<\\/"))
    )
