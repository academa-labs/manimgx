"""The manimgx command line: a scene rendered to video, drawn as stills, checked, presented,
and previewed live.

    manimgx render scene.py [Scene] [-o video.mp4]      the video, a storyboard, layout problems
    manimgx still scene.py [Scene] [-t 0,2.5,end]       frames at those times, on one sheet
    manimgx check scene.py [Scene]                      timeline, storyboard, layout problems
    manimgx present scene.py [Scene]                    its sections as slides, in the browser
    manimgx preview scene.py [Scene]                    a window playing it, again on each save

What a command writes goes to stdout, one line per file, then its report; errors go to stderr.
Exit 0 on success, 1 when the scene fails (or `check` finds problems), 2 when the command is
wrong. Help is plain text when piped (an agent's shell), rich on a terminal.
"""

import sys

from manimgx import _engine

# A command that draws starts the GPU before the rest of the command line loads (its modules,
# then the scene's file), so that the GPU comes up meanwhile; `--version`, `--help` and
# `preview` (its window draws its takes) never bring it up.
DRAWING = ("render", "still", "check", "present")
if sys.argv[1:2] and sys.argv[1] in DRAWING and not {"-h", "--help"} & set(sys.argv):
    _engine.start_gpu()

from importlib.metadata import version
from typing import Annotated

import typer

from manimgx.cli.export import check, present, render, still
from manimgx.cli.preview import preview

app = typer.Typer(
    name="manimgx",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich" if sys.stdout.isatty() else None,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version(shown: bool) -> None:
    if shown:
        typer.echo(f"manimgx {version('manimgx')}")
        raise typer.Exit


@app.callback()
def manimgx(
    _: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Render Manim Community Edition scenes on a fast GPU engine.

    A scene file is Manim CE code: `import manimgx as m`, a class deriving m.Scene, its
    `construct`. Work in a loop:

    \b
        manimgx check scene.py              timeline, storyboard, layout problems
        manimgx still scene.py -t 1.5,end   the frames at 1.5 s and at the end
        manimgx render scene.py             the video (MP4), with the same report

    Files are written beside the scene file; each command prints what it wrote."""


app.command()(render)
app.command()(still)
app.command()(check)
app.command()(preview)
app.command()(present)


def main() -> None:
    app(prog_name="manimgx")
