"""`manimgx preview`: a scene in ManimGX's player, in a window of its own, made again each time
its code is saved.

Each generation runs in a fresh child process, with its film recorded as a take (see
[`Film`][manimgx.Film]) and sent to a [`Window`][manimgx.Window], which plays it as it is made.
On a save the running child stops and a pre-started child reads the current source. Its new
take replaces the old at the same moment, once it gets there: an edit never loses the place. An
error is shown over the last good take.
"""

import contextlib
import json
import multiprocessing
import sys
import time
import traceback
from collections.abc import Iterable
from importlib.machinery import (
    BYTECODE_SUFFIXES,
    EXTENSION_SUFFIXES,
    SOURCE_SUFFIXES,
    ExtensionFileLoader,
    FileFinder,
    SourcelessFileLoader,
)
from multiprocessing.connection import Connection
from pathlib import Path
from types import CodeType
from typing import Annotated

import typer

from manimgx import _engine
from manimgx.cli.scenes import (
    File,
    Format,
    Fps,
    Mistake,
    Resolution,
    SceneName,
    Size,
    Source,
    fail,
    load,
    pick,
    report_error,
    scenes,
)
from manimgx.rendering.film import Cut
from manimgx.rendering.window import Window
from manimgx.settings import config

POLL = 0.02  # seconds between looks at the files


def preview(
    file: File,
    name: SceneName = None,
    time_: Annotated[
        float,
        typer.Option(
            "--time", "-t", min=0, help="Where the playhead starts, in seconds."
        ),
    ] = 0.0,
    resolution: Resolution = None,
    fps: Fps = None,
) -> None:
    """Preview a scene live: in a window, made again each time its code is saved.

    The window plays the scene as it is made. Saving the file, or a module it imports from
    beside it, runs the scene again, and the window keeps its place; an error shows over the
    last good picture. A file of several scenes plays the one named, or its first; N and P go
    to the others. Keys: Space play/pause, ← → 5 s, , . a frame, Option (or Ctrl) with ← → a
    play, ? all of them. Closing the window, or Ctrl+C, stops."""
    if not file.is_file():
        raise fail(f"error: {file}: no such file")
    with Window(f"{file.name} - ManimGX", time=time_) as window:
        standby = Generation()
        try:
            files = [file]
            while window.open:
                news = News(files, window)
                with contextlib.closing(standby) as child:
                    standby = Generation()
                    files = child.run(file, name, resolution, fps, window, news)
                while window.open and not news():
                    time.sleep(POLL)
                if news.asked is not None:
                    name = news.asked
                else:
                    time.sleep(POLL)
        except KeyboardInterrupt:
            pass
        finally:
            standby.close()
    if window.failure is not None:
        raise fail(f"error: the window: {window.failure}", 1)


class News:
    """What makes a run out of date: a file it reads saved again, or another scene asked for
    in the window. Called, whether there is any (it looks every `POLL` seconds)."""

    def __init__(self, files: list[Path], window: Window) -> None:
        self.seen = stamps(files)
        self.window = window
        self.asked: str | None = None
        self.looked = time.monotonic()

    def watch(self, seen: dict[Path, int]) -> None:
        """Watch sources from the instant the child read them, even if delivery was delayed."""
        for file, stamp in seen.items():
            self.seen.setdefault(file, stamp)

    def __call__(self) -> bool:
        now = time.monotonic()
        if now - self.looked < POLL:
            return False
        self.looked = now
        self.asked = self.window.asked() or self.asked
        return self.asked is not None or stamps(self.seen) != self.seen


class Generation:
    """A fresh interpreter, warmed before it is asked to read and render one scene."""

    def __init__(self) -> None:
        context = multiprocessing.get_context("spawn")
        self.pipe, child = context.Pipe()
        self.process = context.Process(target=_generation, args=(child,))
        self.process.start()
        child.close()

    def run(
        self,
        file: Path,
        name: str | None,
        resolution: Size | None,
        fps: int | None,
        window: Window,
        news: News,
    ) -> list[Path]:
        """Relay its take, watch its sources and return the files this generation read."""
        files = {file}
        self.pipe.send((file, name, resolution, fps))
        while window.open and not news():
            if not self.pipe.poll(POLL):
                continue
            try:
                message: bytes | dict[Path, int] | None = self.pipe.recv()
            except EOFError:
                self.process.join(timeout=POLL)
                error = RuntimeError(
                    f"preview child exited with code {self.process.exitcode}"
                )
                window.failed(error, str(error))
                break
            if message is None:
                break
            if isinstance(message, dict):
                news.watch(message)
                files.update(message)
            else:
                try:
                    window(message)
                except Cut:
                    break
        return list(files)

    def close(self) -> None:
        """Stop and reap the child, including one still executing author code."""
        if self.pipe.closed:
            return
        self.process.join(timeout=POLL)
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=1)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()
        self.pipe.close()
        self.process.close()


def _generation(pipe: Connection) -> None:
    """Read source only after the request; send dependencies, take bytes and completion."""
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    with pipe:
        file, name, resolution, fps = pipe.recv()
        root = file.resolve().parent
        started = time.perf_counter()

        class WatchedSource(Source):
            def get_code(self, fullname: str) -> CodeType:
                path = Path(self.path).absolute()
                pipe.send(stamps([path]))
                return super().get_code(fullname)

        # Every newly imported source is current, even after a same-timestamp edit.
        # Python still owns package, namespace, extension and circular import resolution.
        sys.path_hooks.insert(
            0,
            FileFinder.path_hook(
                (ExtensionFileLoader, EXTENSION_SUFFIXES),
                (WatchedSource, SOURCE_SUFFIXES),
                (SourcelessFileLoader, BYTECODE_SUFFIXES),
            ),
        )
        sys.path_importer_cache.clear()
        try:
            module = load(file)
            found = [s.__name__ for s in scenes(module)]
            kind = pick(
                file, module, found[0] if name is None and len(found) > 1 else name
            )
            pipe.send(
                _engine.note(json.dumps({"scenes": found, "scene": kind.__name__}))
            )
            look = Format.own(resolution, fps)
            config.pixel_width, config.pixel_height = look.width, look.height
            config.frame_rate = look.fps
            film = kind().render(take=pipe.send)
            typer.echo(
                f"{kind.__name__}: {film.frame_count} frames in"
                f" {time.perf_counter() - started:.2f} s",
                err=True,
            )
        except BaseException as error:
            text = str(error) if isinstance(error, Mistake) else report_error(error)
            typer.echo(text, err=True)
            own = [
                f
                for f in traceback.extract_tb(error.__traceback__)
                if Path(f.filename).resolve().is_relative_to(root)
            ]
            with contextlib.suppress(BrokenPipeError):
                pipe.send(
                    _engine.note(
                        json.dumps(
                            {
                                "error": {
                                    "message": str(error),
                                    "type": type(error).__name__,
                                    "trace": text,
                                    "line": own[-1].lineno
                                    if own
                                    else getattr(error, "lineno", None),
                                }
                            }
                        )
                    )
                )
        finally:
            with contextlib.suppress(BrokenPipeError):
                pipe.send(None)


def stamps(paths: Iterable[Path]) -> dict[Path, int]:
    """The files' modification times (0 for one that is gone, for now)."""
    seen = {}
    for path in paths:
        try:
            seen[path] = path.stat().st_mtime_ns
        except FileNotFoundError:
            seen[path] = 0
    return seen
