"""The docs' examples, rendered: a Python block that defines a scene is shown with its film.

`python -m docs.examples [PATH...]` gathers the example films (`examples/`) and the Python
blocks of the pages (`content/`), the README and the docstrings (`src/manimgx/`), and renders each scene
among them — those written under the given paths, if any — into `content/films/`: a still of
its last frame with anything on it, and a video too if anything moves. A film is named after its scene and
a digest of its inputs. Completed outputs and their checksums are kept in `.cache/films/`;
`--cache-key` prints the key and compatible prefix for carrying these files between builds.
GitHub and PyPI play no video,
so a README scene is also `readme-<scene>.svg`, a name the README can show: the scene as an
SVG that plays itself (`docs.svg`).

While the site builds, `fence` (SuperFences' formatter for Python blocks, set in
`docs/zensical.toml`) puts each block's film above its code.
"""

import argparse
import ast
import hashlib
import html
import json
import os
import platform
import re
import shutil
import sys
import textwrap
import types
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from functools import cache, cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from markdown import Markdown
    from pymdownx.superfences import SuperFencesBlockPreprocessor

    from manimgx import Scene

DOCS = Path(__file__).parent
ROOT = DOCS.parent
PAGES = DOCS / "content"
README = DOCS.parent / "README.md"
SOURCE = DOCS.parent / "src" / "manimgx"
FILMS = PAGES / "films"
VOICE = DOCS / "voice"
RECORDS = DOCS / ".cache" / "films"
URL = "/films"
OUTPUTS = (".webp", ".mp4", ".svg", "-light.svg")
# Shared inputs are deliberately conservative: even a Python docstring is observable at
# runtime. Scene-specific code is hashed separately, so Markdown prose changes no film and
# editing one standalone example changes only its film. Keep assets read by examples in
# docs/assets/ or docs/voice/; generated pages and outputs are never inputs.
INPUTS = (
    "src/manimgx/**/*.py",
    "rust/Cargo.*",
    "rust/*/Cargo.toml",
    "rust/*/build.rs",
    "rust/*/src/**/*",
    "rust/mitex-spec-gen/lib.typ",
    "rust/mitex-spec-gen/spec.rkyv",
    "rust/.cargo/**/*",
    "rust/rust-toolchain*",
    "rust-toolchain*",
    "fonts/*/pyproject.toml",
    "fonts/*/src/**/*",
    "docs/assets/**/*",
    "docs/voice/**/*",
    "docs/examples.py",
    "docs/svg.py",
    "pyproject.toml",
    "uv.lock",
)
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


@cache
def render_context() -> str:
    """The shared renderer and its environment, independent of paths and Git history.

    CI names its actual driver/toolchain versions in MANIMGX_DOCS_RENDER_PROFILE. Local
    caches stay on their own machine and OS version; they do not assume two GPUs agree.
    """
    profile = os.environ.get("MANIMGX_DOCS_RENDER_PROFILE") or (
        f"{platform.node()}:{platform.release()}"
    )
    environment = (
        sys.implementation.name,
        platform.python_version(),
        sys.platform,
        platform.machine(),
        profile,
    )
    digest = hashlib.sha256(json.dumps(environment).encode())
    paths = sorted({path for pattern in INPUTS for path in ROOT.glob(pattern)})
    for path in paths:
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
            digest.update(bytes.fromhex(_digest(path)))
    return digest.hexdigest()


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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
        """Its film's name: the scene's, and a digest of its code and shared render inputs."""
        code = textwrap.dedent(self.code).strip() + "\n"
        digest = hashlib.sha256(
            f"{render_context()}\n{FORMAT}\n{code}".encode()
        ).hexdigest()[:20]
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
    """Every scene's source; the generated Gallery is a view of examples/, not an input."""
    found = [
        block
        for page in [*sorted(PAGES.rglob("*.md")), README]
        if not page.is_relative_to(PAGES / "gallery")
        for block in blocks(page.read_text(encoding="utf-8"), page)
    ]
    found += [
        Example(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())
        for path in sorted((ROOT / "examples").glob("*.py"))
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
    """Publish an example only after all its outputs have finished successfully.

    The completion record is replaced last. A crash during publication leaves a missing
    or mismatched checksum, which the next build repairs. Staging files live outside the
    site and are never cached.
    """
    FILMS.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=RECORDS.parent, prefix="render-") as temporary:
        folder = Path(temporary)
        _draw(example, folder, readme)
        files = {
            suffix: _digest(path)
            for suffix in OUTPUTS
            if (path := folder / f"{example.stem}{suffix}").is_file()
        }
        record = folder / f"{example.stem}.json"
        record.write_text(json.dumps(files, sort_keys=True) + "\n", encoding="utf-8")
        for suffix in OUTPUTS:
            target = FILMS / f"{example.stem}{suffix}"
            if suffix in files:
                (folder / target.name).replace(target)
            else:
                target.unlink(missing_ok=True)
        record.replace(RECORDS / record.name)


def _draw(example: Example, folder: Path, readme: bool) -> None:
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

    video = folder / f"{example.stem}.mp4"
    size = m.config.pixel_width, m.config.pixel_height
    scene().render(video, frames=keep, preset=PRESET, crf=CRF)
    still = Image.frombytes("RGBA", size, poster).convert("RGB")
    still.save(folder / f"{example.stem}.webp", quality=90, method=6)
    if drawn == 1:  # nothing moves: the still is the film
        video.unlink()
    if readme:
        recording = svg.record(scene)
        svg.write(recording, folder / f"{example.stem}.svg")
        svg.write(recording, folder / f"{example.stem}-light.svg", light=True)


def scenes() -> dict[str, Example]:
    """The unique scenes, rejecting conflicting definitions before any work is done."""
    scenes: dict[str, Example] = {}
    for example in examples():
        seen = scenes.setdefault(str(example.scene), example)
        if seen.stem != example.stem:
            sys.exit(
                f"{example.where}: {example.scene} is also defined at {seen.where}"
                " (a scene's name is its film's: it must be unique)"
            )
    return scenes


def cache_key() -> dict[str, str]:
    """An immutable snapshot key, and the prefix of snapshots with compatible renderers."""
    readme = _readme()
    inventory = sorted((name, e.stem, name in readme) for name, e in scenes().items())
    digest = hashlib.sha256(json.dumps(inventory).encode()).hexdigest()
    prefix = f"docs-films-v1-{render_context()}-"
    return {"key": prefix + digest, "prefix": prefix}


def main(only: list[str], jobs: int | None = None) -> None:
    """Render missing or damaged films, and discard outputs no current example owns."""
    FILMS.mkdir(parents=True, exist_ok=True)
    scenes_to_render = scenes()
    readme = _readme()
    if only:
        scenes_to_render = {
            name: e
            for name, e in scenes_to_render.items()
            if e.where.startswith(tuple(only))
        }
    else:
        stems = {example.stem for example in scenes_to_render.values()}
        for record in RECORDS.glob("*.json"):
            if record.stem not in stems:
                record.unlink()
        shown = {e.stem for e in scenes_to_render.values() if e.scene in readme}
        shown |= {f"readme-{name}" for name in readme}
        stems |= shown | {f"{stem}-light" for stem in shown}
        for (
            film
        ) in FILMS.iterdir():  # a film's files: <stem>.webp, .mp4, .svg, -light.svg
            if film.name.split(".")[0] not in stems:
                film.unlink()
    todo = [e for e in scenes_to_render.values() if not _rendered(e, e.scene in readme)]
    if todo:  # a long render shows nothing until it ends: say what is being made
        names = ", ".join(str(e.scene) for e in todo[:6])
        print(f"rendering {len(todo)}: {names}{', ...' * (len(todo) > 6)}", flush=True)
    failed = 0
    with ProcessPoolExecutor(max_workers=jobs, max_tasks_per_child=1) as pool:
        futures = {pool.submit(render, e, e.scene in readme): e for e in todo}
        for done, future in enumerate(as_completed(futures), 1):
            example = futures[future]
            if (error := future.exception()) is not None:
                failed += 1
                print(f"{example.where}: {example.scene} failed: {error!r}", flush=True)
            else:
                print(f"[{done}/{len(todo)}] {example.scene}", flush=True)
    print(
        f"{len(scenes_to_render)} scenes: {len(todo) - failed} rendered, {failed} failed"
    )
    for example in scenes_to_render.values():
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
    """A completed render has exactly the files recorded, with the same contents."""
    required = {".webp", ".svg", "-light.svg"} if readme else {".webp"}
    try:
        files = json.loads(
            (RECORDS / f"{example.stem}.json").read_text(encoding="utf-8")
        )
        if not isinstance(files, dict) or not required <= files.keys() <= set(OUTPUTS):
            return False
        return all(
            _digest(path) == files[suffix] if suffix in files else not path.exists()
            for suffix in OUTPUTS
            for path in [FILMS / f"{example.stem}{suffix}"]
        )
    except (OSError, ValueError):
        return False


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", help="render only examples under these source paths"
    )
    parser.add_argument(
        "--jobs", type=int, help="number of simultaneous render processes"
    )
    parser.add_argument(
        "--cache-key",
        action="store_true",
        help="print the cache key and restore prefix as JSON",
    )
    args = parser.parse_args()
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.cache_key:
        print(json.dumps(cache_key()))
    else:
        main(args.paths, args.jobs)
