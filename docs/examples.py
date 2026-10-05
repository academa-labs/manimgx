"""The docs' examples, rendered: a Python block that defines a scene is shown with its film.

`python -m docs.examples [PATH...]` gathers the Python blocks of the pages (`content/`), of
the README and of the docstrings (`src/manimgx/`) and renders each scene
among them — those written under the given paths, if any — into `content/films/`: a still of
its last frame with anything on it, and a video too if anything moves. A film is named after its scene and
a digest of its code, so an example renders once per version. GitHub and PyPI play no video,
so a README scene is also `readme-<scene>.svg`, a name the README can show: the scene as an
SVG that plays itself (`docs.svg`).

While the site builds, `fence` (SuperFences' formatter for Python blocks, set in
`docs/zensical.toml`) puts each block's film above its code.
"""

import ast
import hashlib
import html
import importlib
import re
import shutil
import sys
import textwrap
import types
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from markdown import Markdown
    from pymdownx.superfences import SuperFencesBlockPreprocessor

    from manimgx import Scene

DOCS = Path(__file__).parent
PAGES = DOCS / "content"
README = DOCS.parent / "README.md"
SOURCE = DOCS.parent / "src" / "manimgx"
FILMS = PAGES / "films"
VOICE = DOCS / "voice"
URL = "/films"
# how a film is made: at the films' own rate (60 frames a second, the default), encoded for the
# web, where slow and CRF 28 make a tenth of the default's file (ultrafast, 18), alike to the eye,
# in the same time. A film's name digests this with its code, so a change here makes them again.
SIZE, FPS = (1280, 720), 60
PRESET, CRF = "slow", 28
FORMAT = f"{SIZE[0]}x{SIZE[1]} at {FPS} fps, {PRESET}, CRF {CRF}"

FENCE = re.compile(
    r"^(?P<indent>[ \t]*)```(?:python|py)\b[^\n]*\n(?P<code>.*?)^(?P=indent)```",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class Example:
    """A Python block of the docs, and where it is written (`path:line`)."""

    code: str
    where: str = ""

    @cached_property
    def scene(self) -> str | None:
        """The scene it renders: the last class it defines on a scene, if any."""
        try:
            tree = ast.parse(self.code)
        except SyntaxError:
            return None
        scenes: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(
                (name := _name(base)).endswith("Scene") or name in scenes
                for base in node.bases
            ):
                scenes.append(node.name)
        return scenes[-1] if scenes else None

    @cached_property
    def stem(self) -> str:
        """Its film's name: the scene's, and a digest of the code and of how films are
        made (`FORMAT`)."""
        code = textwrap.dedent(self.code).strip() + "\n"
        digest = hashlib.sha256(f"{FORMAT}\n{code}".encode()).hexdigest()[:10]
        return f"{self.scene}-{digest}"


def _name(node: ast.expr) -> str:
    """A base class as written, by its last name (`Scene` and `m.Scene` are "Scene")."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def blocks(text: str, path: Path, line: int = 1) -> list[Example]:
    """The Python blocks of a text written in a file (from a given line of it)."""
    where = path.relative_to(DOCS.parent)
    return [
        Example(
            textwrap.dedent(match["code"]),
            f"{where}:{line + text.count(chr(10), 0, match.start())}",
        )
        for match in FENCE.finditer(text)
    ]


def examples() -> list[Example]:
    """Every scene the docs show: the pages', the README's, then the docstrings'."""
    found = [
        block
        for page in [*sorted(PAGES.rglob("*.md")), README]
        for block in blocks(page.read_text(encoding="utf-8"), page)
    ]
    for module in sorted(SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ) and (doc := ast.get_docstring(node)):
                found += blocks(doc, module, node.body[0].lineno)
    return [example for example in found if example.scene is not None]


def load(example: Example) -> "type[Scene]":
    """An example's scene, its code run as a module whose file is in docs/: a narrated
    example keeps what it says in docs/voice/ (committed, so the build speaks only a line
    that is new)."""
    import manimgx as m

    module = types.ModuleType("__example__")
    module.__file__ = str(VOICE.parent / "examples.py")
    sys.modules[module.__name__] = module
    exec(compile(example.code, example.where, "exec"), module.__dict__)
    scene = module.__dict__[str(example.scene)]
    if not (isinstance(scene, type) and issubclass(scene, m.Scene)):
        raise TypeError(f"{example.scene} is not a scene")
    return scene


def render(example: Example, readme: bool = False) -> None:
    """Render an example's scene into its film — in a process of its own, since an example
    may change the configuration — and, for the README's, into its SVGs too: one for a dark
    page, one for a light page (`<stem>-light.svg`)."""
    from docs import svg
    from PIL import Image

    import manimgx as m
    from manimgx.rendering.film import Frame

    m.config.pixel_width, m.config.pixel_height = SIZE
    m.config.frame_rate = FPS
    scene = load(example)
    drawn, poster = 0, b""

    def keep(frame: Frame) -> None:
        """Count the frames (each is sent once, however long it holds), and keep the last one
        with anything on it: a scene that ends empty is shown as it was before."""
        nonlocal drawn, poster
        drawn += 1
        pixels = frame.pixels()
        if not poster or pixels.count(pixels[:4]) * 4 != len(pixels):
            poster = pixels

    video = FILMS / f"{example.stem}.mp4"
    size = m.config.pixel_width, m.config.pixel_height
    scene().render(video, frames=keep, preset=PRESET, crf=CRF)
    still = Image.frombytes("RGBA", size, poster).convert("RGB")
    still.save(FILMS / f"{example.stem}.webp", quality=90, method=6)
    if drawn == 1:  # nothing moves: the still is the film
        video.unlink()
    if readme:
        recording = svg.record(scene)
        svg.write(recording, FILMS / f"{example.stem}.svg")
        svg.write(recording, FILMS / f"{example.stem}-light.svg", light=True)


def main(only: list[str]) -> None:
    """Render every example whose film is missing — only those written under the paths in
    `only`, if any — and, rendering them all, delete the films of none."""
    importlib.import_module("manimgx")  # fail once if the shared runtime cannot load
    FILMS.mkdir(parents=True, exist_ok=True)
    scenes: dict[str, Example] = {}
    for example in examples():
        seen = scenes.setdefault(str(example.scene), example)
        if seen.stem != example.stem:
            sys.exit(
                f"{example.where}: {example.scene} is also defined at {seen.where}"
                " (a scene's name is its film's: it must be unique)"
            )
    readme = _readme()
    if only:
        scenes = {
            name: e for name, e in scenes.items() if e.where.startswith(tuple(only))
        }
    else:
        stems = {example.stem for example in scenes.values()}
        shown = {e.stem for e in scenes.values() if e.scene in readme}
        shown |= {f"readme-{name}" for name in readme}
        stems |= shown | {f"{stem}-light" for stem in shown}
        for (
            film
        ) in FILMS.iterdir():  # a film's files: <stem>.webp, .mp4, .svg, -light.svg
            if film.name.split(".")[0] not in stems:
                film.unlink()
    todo = [e for e in scenes.values() if not _rendered(e, e.scene in readme)]
    if todo:  # a long render shows nothing until it ends: say what is being made
        names = ", ".join(str(e.scene) for e in todo[:6])
        print(f"rendering {len(todo)}: {names}{', ...' * (len(todo) > 6)}", flush=True)
    failed = 0
    with ProcessPoolExecutor(max_tasks_per_child=1) as pool:
        futures = {pool.submit(render, e, e.scene in readme): e for e in todo}
        for done, future in enumerate(as_completed(futures), 1):
            example = futures[future]
            if (error := future.exception()) is not None:
                failed += 1
                print(f"{example.where}: {example.scene} failed: {error!r}")
            else:
                print(f"[{done}/{len(todo)}] {example.scene}")
    print(f"{len(scenes)} scenes: {len(todo) - failed} rendered, {failed} failed")
    for example in scenes.values():
        for variant in ("", "-light") if example.scene in readme else ():
            if (film := FILMS / f"{example.stem}{variant}.svg").exists():
                shutil.copyfile(film, FILMS / f"readme-{example.scene}{variant}.svg")
    if failed:
        sys.exit(1)


def _readme() -> set[str]:
    """The names of the README's scenes, which it shows under names of their own."""
    text = README.read_text(encoding="utf-8")
    return {str(e.scene) for e in blocks(text, README) if e.scene}


def _rendered(example: Example, readme: bool) -> bool:
    """Whether an example's film is made: its still, and, for the README's, its SVGs (a
    scene rendered before the README showed it has none yet)."""
    film = FILMS / example.stem
    return film.with_suffix(".webp").exists() and (
        not readme
        or all((FILMS / f"{example.stem}{v}.svg").exists() for v in ("", "-light"))
    )


def validate(
    language: str,
    inputs: dict[str, str],
    options: dict[str, object],
    attrs: dict[str, object],
    md: "Markdown",
) -> bool:
    """SuperFences' validator for Python blocks: Highlight's options (a title, line
    numbers, lines to mark), and `fold` and `show`, which `fence` takes (an option the
    validator leaves unknown fails the block)."""
    from pymdownx.superfences import highlight_validator

    if (fold := inputs.pop("fold", None)) is not None:
        options["fold"] = fold
    if (show := inputs.pop("show", None)) is not None:
        if show not in ("code", "film"):
            return False
        options["show"] = show
    return highlight_validator(language, inputs, options, attrs, md)


def fence(
    source: str,
    language: str,
    class_name: str,
    options: dict[str, object],
    md: "Markdown",
    **kwargs: object,
) -> str:
    """SuperFences' formatter for Python blocks: the block highlighted as any other, under
    its scene's film if it has one. A block marked `fold` (a gallery film's file) is folded
    under its title, the film above it. `show="code"` shows the code alone and
    `show="film"` the film alone, so that a page can put words between a program and its
    video (the two blocks hold the same code: a scene's name is its film's, one film)."""
    fenced = cast("SuperFencesBlockPreprocessor", md.preprocessors["fenced_code_block"])
    fold = options.pop("fold", None) is not None
    show = options.pop("show", None)
    title = options.pop("title", "Code") if fold else None
    film = None if show == "code" else _film(Example(source))
    if show == "film":
        return "" if film is None else f'<figure class="mx-example">{film}</figure>'
    code = fenced.highlight(
        src=source, language=language, options=options, md=md, **kwargs
    )
    if fold:
        code = (
            f'<details class="mx-code"><summary>{html.escape(str(title))}</summary>'
            f"{code}</details>"
        )
    return code if film is None else f'<figure class="mx-example">{film}{code}</figure>'


def _film(example: Example) -> str | None:
    """A rendered example's film, as HTML: its video, or its still if nothing moves. A
    film taller than wide (9:16) is marked, so that it is not as wide as the page."""
    if example.scene is None or not (still := FILMS / f"{example.stem}.webp").exists():
        return None
    from PIL import Image

    with Image.open(still) as image:
        width, height = image.size
    size = f'width="{width}" height="{height}"'
    kind = "mx-film mx-film--tall" if height > width else "mx-film"
    if (FILMS / f"{example.stem}.mp4").exists():
        return (
            f'<video class="{kind}" src="{URL}/{example.stem}.mp4"'
            f' poster="{URL}/{still.name}" {size} aria-label="{example.scene}"'
            ' muted loop playsinline controls preload="none"></video>'
        )
    return (
        f'<img class="{kind}" src="{URL}/{still.name}" {size}'
        f' alt="{example.scene}" loading="lazy">'
    )


if __name__ == "__main__":
    main(sys.argv[1:])
