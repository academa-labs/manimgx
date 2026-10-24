"""Preview generations read current source in fresh processes and leave their host alone."""

import json
import multiprocessing
import os
import py_compile
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from tests.preview import Viewer

from manimgx.cli.preview import Generation, News
from manimgx.rendering.window import Window


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(entry: Path, child: Generation) -> tuple[Viewer, News]:
    window = Viewer("test")
    news = News([entry], cast("Window", window))
    child.run(entry, None, None, None, cast("Window", window), news)
    return window, news


def loaded(entry: Path) -> tuple[object, set[Path]]:
    """A module's value and sources, as a fresh preview generation sees them."""
    with entry.open("a", encoding="utf-8") as file:
        file.write(
            "\nimport json\nfrom pathlib import Path\n"
            "Path(__file__).with_suffix('.json').write_text(json.dumps(value))\n"
            "import manimgx as m\nclass Loaded(m.Scene): pass\n"
        )
    with closing(Generation()) as child:
        window, news = run(entry, child)
    assert not [n for n in window.notes() if "error" in n]
    return json.loads(entry.with_suffix(".json").read_text(encoding="utf-8")), set(
        news.seen
    )


def test_same_timestamp_helper_edits_use_current_source_and_preserve_bytecode(
    tmp_path: Path,
) -> None:
    """A generation reads its helper's bytes even when timestamp bytecode still matches."""
    entry, helper = tmp_path / "entry.py", tmp_path / "nearby.py"
    write(helper, "value = 'one'\n")
    stamp = helper.stat()
    cached = py_compile.compile(str(helper), doraise=True)
    assert cached is not None
    original = Path(cached).read_bytes()
    for value in ("two", "six"):
        write(entry, "from nearby import value\n")
        write(helper, f"value = '{value}'\n")
        os.utime(helper, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        got, files = loaded(entry)
        assert got == value
        assert {entry, helper} <= files
        assert Path(cached).read_bytes() == original
        assert "nearby" not in sys.modules


def test_package_imports_read_encoded_source_and_resources(tmp_path: Path) -> None:
    """Relative imports and resource reads retain the interpreter's package semantics."""
    entry = tmp_path / "entry.py"
    write(entry, "from own_package import value\n")
    write(tmp_path / "own_package/__init__.py", "from .part import value\n")
    part = tmp_path / "own_package/part.py"
    part.write_bytes(
        b"# coding: latin-1\nfrom importlib.resources import files\n"
        b"value = 'caf\xe9' + files(__package__).joinpath('note.txt').read_text()\n"
    )
    write(tmp_path / "own_package/note.txt", "!")
    value, files = loaded(entry)
    assert value == "café!"
    assert part in files
    assert not (tmp_path / "own_package/__pycache__").exists()


@pytest.mark.parametrize("failure", ["entry", "compile", "execute", "render"])
def test_failed_generations_report_their_error_and_keep_their_sources(
    tmp_path: Path, failure: str
) -> None:
    """Every failed generation reports its error and watches sources read before failure."""
    entry, helper = tmp_path / "entry.py", tmp_path / "broken.py"
    write(
        entry,
        "!\n"
        if failure == "entry"
        else "import broken\nimport manimgx as m\n"
        "class Broken(m.Scene):\n    def construct(self): raise RuntimeError('render')\n",
    )
    write(
        helper,
        "!\n"
        if failure == "compile"
        else "raise RuntimeError('execution')\n"
        if failure == "execute"
        else "value = 1\n",
    )
    before = sys.meta_path.copy(), sys.path.copy(), dict(sys.modules)
    with closing(Generation()) as child:
        window, news = run(entry, child)
    assert any("error" in n for n in window.notes())
    assert entry in news.seen
    if failure != "entry":
        assert helper in news.seen
    assert (sys.meta_path, sys.path) == before[:2]
    assert all(sys.modules.get(k) is v for k, v in before[2].items())


def test_namespace_packages_circular_imports_and_symlinks_use_current_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All source dependencies are watched, including other namespace roots and symlinks."""
    root, external = tmp_path / "project", tmp_path / "external"
    entry, helper = root / "entry.py", external / "shared/elsewhere.py"
    write(helper, "value = 19\n")
    write(root / "shared/nearby.py", "value = 23\n")
    write(root / "cycle_a.py", "value = 2\nimport cycle_b\n")
    write(root / "cycle_b.py", "import cycle_a\nvalue = cycle_a.value + 1\n")
    target = tmp_path / "shared.py"
    write(target, "value = 1\n")
    linked = root / "linked.py"
    linked.symlink_to(target)
    monkeypatch.syspath_prepend(str(external))
    for value in (19, 20):
        write(helper, f"value = {value}\n")
        write(
            entry,
            "import shared.elsewhere, shared.nearby, cycle_a, linked\n"
            "value = shared.elsewhere.value + shared.nearby.value + cycle_a.cycle_b.value + linked.value\n",
        )
        got, files = loaded(entry)
        assert got == value + 27
        assert {helper, linked} <= files


def test_a_save_stops_a_child_even_when_author_code_never_yields(
    tmp_path: Path,
) -> None:
    """The parent can cancel a busy generation without waiting for a frame or an import."""
    entry, marker = tmp_path / "entry.py", tmp_path / "began"
    write(
        entry,
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nwhile True: pass\n",
    )
    window = Viewer("test")

    class Edited(News):
        def __call__(self) -> bool:
            return marker.exists()

    started = time.monotonic()
    with closing(Generation()) as child:
        pid = child.process.pid
        child.run(
            entry,
            None,
            None,
            None,
            cast("Window", window),
            Edited([entry], cast("Window", window)),
        )
    assert time.monotonic() - started < 5
    child.close()
    assert pid not in [c.pid for c in multiprocessing.active_children()]


STATEMENTS = (
    "m.Circle.set_default(color=m.RED)",
    "m.Dot.set_default(radius=0.3)",
    "m.config.background_color = m.WHITE",
    "m.config.frame_rate = 30",
    "m.config.pixel_width, m.config.pixel_height = 640, 360",
)
SHOWN = """
import json
from pathlib import Path
class Shown(m.Scene):
    def construct(self):
        self.shown = [m.Circle(), m.Square(), m.Dot().shift(m.RIGHT)]
        self.add(*self.shown)
        self.play(m.Rotate(self.shown[1], 1.0), run_time=0.5)
    def render(self, **kwargs):
        film = super().render(**kwargs)
        shown = [[mob.get_color().to_hex(), float(mob.get_fill_opacity()), round(mob.width, 9)] for mob in self.shown]
        Path(__file__).with_suffix('.json').write_text(json.dumps([film.frame_count, str(film.fps), self.camera.background_color.to_hex(), shown]))
        return film
"""


@settings(max_examples=12)
@given(
    runs=st.lists(
        st.frozensets(st.sampled_from(STATEMENTS), max_size=3), min_size=2, max_size=3
    )
)
@example(runs=[frozenset({"m.Circle.set_default(color=m.RED)"}), frozenset()])
def test_a_preview_generation_shows_what_a_fresh_process_shows(
    runs: list[frozenset[str]],
) -> None:
    """Each pre-started child sees current source and no earlier generation's library state."""
    with tempfile.TemporaryDirectory() as folder:
        entry = Path(folder, "scene.py")
        for statements in runs:
            with closing(Generation()) as child:
                write(
                    entry,
                    "import manimgx as m\n"
                    + "\n".join(sorted(statements))
                    + "\n"
                    + SHOWN,
                )
                window, _ = run(entry, child)
            assert not [n for n in window.notes() if "error" in n]
            seen = json.loads(entry.with_suffix(".json").read_text(encoding="utf-8"))
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; from manimgx.cli.scenes import load, pick; "
                    "import sys; file=Path(sys.argv[1]); pick(file, load(file), None)().render(take=lambda data: None)",
                    str(entry),
                ],
                check=True,
                capture_output=True,
            )
            assert (
                json.loads(entry.with_suffix(".json").read_text(encoding="utf-8"))
                == seen
            )


def test_delayed_source_notifications_still_detect_edits(tmp_path: Path) -> None:
    """A helper edited after the child read it is stale even before its notification arrives."""
    entry, helper = tmp_path / "entry.py", tmp_path / "helper.py"
    write(entry, "")
    write(helper, "value = 1")
    stamp = helper.stat().st_mtime_ns
    write(helper, "value = 2")
    os.utime(helper, ns=(stamp, stamp + 1_000_000_000))
    window = Viewer("test")
    news = News([entry], cast("Window", window))
    news.watch({helper: stamp})
    news.looked = 0
    assert news()
