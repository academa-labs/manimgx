"""The corpus's tools hold to their rules.

- A stored manimgx film is a baseline whatever CE did and however the case was reviewed:
  `test_regression` fails when its frozen package and today's film differ on the same host,
  and never skips; the first comparison supplies the diagnostics without another render.
- A type report's imprecision is manimgx's: an untyped value from another package is not
  manimgx's output, but manimgx's outputs stay imprecise however untyped their inputs, each
  named by the call or attribute it comes from (a generic class's inherited methods too).
- A type report's escapes are the scene's: every suppression is one, but for a method of the
  scene's own class called through `.animate` or `.always`, which manimgx's types can't name
  (nor is its type manimgx's imprecision).
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
from contextlib import suppress
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from tests.integration import test_corpus as corpus
from tests.integration.corpus import baseline, case, engines, references, typecheck
from tests.integration.corpus.case import (
    FPS,
    METRICS,
    SIZE,
    Case,
    Comparison,
    Facts,
    Failure,
    Frames,
    frames_to_json,
)
from tests.integration.corpus.frozen import Difference

STORED = Frames((("before", 2),), Fraction(1, 5), ((Fraction(0), 2),))


def test_render_deadlines_reap_the_child_and_report_without_killing_pytest(
    tmp_path: Path,
) -> None:
    # Use the corpus test's actual timeout policy with Windows' process-killing method.
    # The child supervisor's deadline starts later; a competing pytest timer wins and
    # kills the worker before its subprocess.run can kill/reap the stalled renderer.
    probe = tmp_path / "test_deadline.py"
    pid = tmp_path / "child.pid"
    finished = tmp_path / "finished"
    probe.write_text(
        f"""
import subprocess
import sys
import time
from pathlib import Path
from tests.integration import test_corpus as corpus
from tests.integration.corpus import engines
from tests.integration.corpus.case import Case, Failure

pytestmark = [mark for mark in corpus.test_regression.pytestmark if mark.name == "timeout"]

def test_supervised_render(monkeypatch):
    children = []
    popen = subprocess.Popen
    def spawn(*args, **kwargs):
        child = popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(child)
        Path({str(pid)!r}).write_text(str(child.pid), encoding="utf-8")
        return child
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setitem(engines.TIMEOUT, "manimgx", 0.5)
    time.sleep(0.25)
    result = engines.run(Case({str(tmp_path)!r}), "manimgx")
    assert isinstance(result.frames, Failure)
    assert "timed out" in result.frames.error
    assert len(children) == 1 and children[0].poll() is not None
    Path({str(finished)!r}).touch()
""",
        encoding="utf-8",
    )
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    try:
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-c",
                str(config),
                str(probe),
                "-n",
                "0",
                "--timeout=0.5",
                "--timeout-method=thread",
                "-q",
            ],
            env=engines.environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        assert finished.exists()
    finally:
        if pid.exists() and not finished.exists():
            # The negative control kills its worker; terminate only the child this probe made.
            with suppress(ProcessLookupError):
                os.kill(int(pid.read_text(encoding="utf-8")), signal.SIGTERM)


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_checkout_preserves_source_and_binary_bytes(
    tmp_path: Path, autocrlf: str
) -> None:
    """Source provenance must survive Windows checkout; image bytes must not change."""
    attributes = case.ROOT / ".gitattributes"
    (tmp_path / ".gitattributes").write_bytes(attributes.read_bytes())
    files = {
        "scene.py": b"import manimgx\n# a scene's reviewed source\n",
        "image.bin": b"\x00\xff\r\n\x01\n\x02",
    }
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)
    git = ["git", "-c", f"core.autocrlf={autocrlf}", "-C", str(tmp_path)]
    subprocess.run([*git, "init", "--quiet"], check=True, capture_output=True)
    subprocess.run([*git, "add", "."], check=True, capture_output=True)
    for name in files:
        (tmp_path / name).unlink()
    subprocess.run([*git, "checkout-index", "--all"], check=True, capture_output=True)
    assert {name: (tmp_path / name).read_bytes() for name in files} == files


@pytest.fixture
def cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty corpus of the test's own."""
    monkeypatch.setattr(case, "CASES", tmp_path)
    return tmp_path


def made(name: str, scene: str) -> Case:
    example = Case(name)
    example.dir.mkdir()
    example.scene.write_text(scene, encoding="utf-8")
    return example


@pytest.mark.usefixtures("cases")
def test_recreated_movie_checksum_binds_its_actual_container_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example = made("recreated", "import manimgx\n")
    example.write_facts(
        Facts(
            example.source_hash(), SIZE, FPS, STORED, Failure("unavailable"), "", None
        )
    )
    example.video_hash("manimgx").write_text(
        f"{hashlib.sha256(b'original encoding').hexdigest()}  manimgx.mkv\n",
        encoding="ascii",
    )
    movie = b"identical decoded frames in a different lossless container"

    def render(_case: Case, _engine: str, *, video: Path) -> engines.Result:
        video.write_bytes(movie)
        return engines.Result(example.source_hash(), STORED)

    monkeypatch.setattr(engines, "run", render)
    facts, _ = references.render(example, {"manimgx"})
    assert facts.manimgx == STORED
    assert example.video("manimgx").read_bytes() == movie
    assert example.video_hash("manimgx").read_text(encoding="ascii") == (
        f"{hashlib.sha256(movie).hexdigest()}  manimgx.mkv\n"
    )


@pytest.mark.usefixtures("cases")
def test_render_evidence_keeps_the_original_complete_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = made("evidence", "import manimgx\n")
    record = {
        "source": example.source_hash(),
        "render": frames_to_json(STORED),
        "duration_exact": "1/5",
        "adapter": {"backend": "test"},
        "differences": [
            {
                "first": 201,
                "repeat": 1,
                "changed_pixels": 7,
                "max_channel_difference": 255,
            }
        ],
    }

    def render(
        command: list[str], **_options: object
    ) -> subprocess.CompletedProcess[str]:
        output = Path(command[command.index("--out") + 1])
        output.write_text(json.dumps(record), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "original render log\n", "")

    monkeypatch.setattr(subprocess, "run", render)
    log = tmp_path / "actual.log"
    result = engines.run(example, "manimgx", log=log)
    assert result.duration == Fraction(1, 5)
    assert log.read_text(encoding="utf-8") == "original render log\n"
    assert (
        json.loads(log.with_suffix(".result.json").read_text(encoding="utf-8"))
        == record
    )


@pytest.mark.usefixtures("cases")
@pytest.mark.parametrize("ce", ["same", "different", "failure"])
@pytest.mark.parametrize("change", ["same", "pixels", "duration", "timeline"])
def test_a_stored_film_holds_whatever_ce_did(
    ce: str, change: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = made("baseline", "import manimgx\n")
    theirs = {"same": STORED, "different": replace(STORED, runs=(("ce", 2),))}
    error = 0.0 if ce == "same" else 255.0
    compared = Comparison(((0, 0, (error,) * len(METRICS)),), ())
    ce_render = theirs.get(ce, Failure("CE cannot render this scene"))
    example.write_facts(
        Facts(example.source_hash(), SIZE, FPS, STORED, ce_render, "", compared)
    )
    output = tmp_path / "diagnostics"
    monkeypatch.setattr(corpus, "DIFFS", output)
    calls = []

    def compare(
        _self: baseline.References, selected: Case, directory: Path
    ) -> engines.Result:
        assert selected == example
        calls.append(selected)
        directory.mkdir(parents=True)
        (directory / "actual.log").write_text(
            "first render's evidence", encoding="utf-8"
        )
        # Host pixels may differ from the canonical movie. Only the frozen package's
        # complete comparison on this same host decides pixel equality.
        frames = replace(STORED, runs=(("host-specific", 2),))
        differences = ()
        if change == "pixels":
            differences = (Difference(201, 1, 7, 255),)
        elif change != "same":
            frames = Failure(f"the candidate changed the reference {change}")
        return engines.Result(example.source_hash(), frames, differences=differences)

    monkeypatch.setattr(baseline.References, "compare", compare)
    references = baseline.References(baseline.Catalog({}, {}), tmp_path / "packages")
    if change == "same":
        corpus.test_regression(example, references)
        assert not (output / example.name).exists()
    else:
        match = (
            "maximum RGB difference 255 at frame 201" if change == "pixels" else change
        )
        with pytest.raises(pytest.fail.Exception, match=match):
            corpus.test_regression(example, references)
        assert (output / example.name / "actual.log").read_text(encoding="utf-8") == (
            "first render's evidence"
        )
    assert calls == [example]


@pytest.mark.usefixtures("cases")
def test_an_untyped_namesake_is_not_manimgxs_output() -> None:
    example = made(
        "external",
        "import manimgx as m\n"
        "import networkx as nx\n"
        "graph = nx.Graph()\n"
        "graph.add_node(0)\n"
        "graph.add_nodes_from([1, 2])\n"
        "graph.add_edge(0, 1)\n"
        "graph.add_edges_from([(1, 2)])\n",
    )
    assert typecheck.imprecise([example]) == {}


def test_typechecking_keeps_an_exact_file_set_beyond_windows_command_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "scènes with spaces"
    directory.mkdir()
    files = [directory / f"{index:04d}_{'scene_' * 10}.py" for index in range(400)]
    for path in files:
        path.write_text(
            'from typing import reveal_type\nwrong: int = "oops"\nreveal_type(42)\n',
            encoding="utf-8",
        )
    unselected = directory / "unselected.py"
    unselected.write_text('wrong: int = "not selected"\n', encoding="utf-8")
    run = subprocess.run

    def windows_sized_command(
        args: list[str],
        *,
        capture_output: bool,
        text: bool,
        cwd: Path,
        check: bool,
        encoding: str = "utf-8",
    ) -> subprocess.CompletedProcess[str]:
        # CreateProcessW includes the terminating NUL in its 32,767 UTF-16-unit limit.
        command = subprocess.list2cmdline(args)
        assert len(command.encode("utf-16-le")) // 2 + 1 <= 32_767
        return run(
            args,
            capture_output=capture_output,
            text=text,
            cwd=cwd,
            check=check,
            encoding=encoding,
        )

    monkeypatch.setattr(subprocess, "run", windows_sized_command)
    diagnostics = typecheck._ty(files, typecheck.STRICT)
    invalid = [
        (path, line)
        for path, line, _, rest in diagnostics
        if "invalid-assignment" in rest
    ]
    assert set(invalid) == {(path.resolve(), 2) for path in files}
    assert len(invalid) == len(files)
    assert typecheck._reveal_positions(files) == {
        (path.resolve(), 3, 13): "Literal[42]" for path in files
    }
    assert typecheck._ty([]) == []
    assert typecheck._reveal_positions([]) == {}


@pytest.mark.usefixtures("cases")
def test_manimgxs_outputs_from_untyped_inputs_are_named_by_their_source() -> None:
    example = made(
        "package",
        "import manimgx as m\n"
        "import networkx as nx\n"
        "def untyped_factory():\n"
        "    return m.Dot()\n"
        "m.always_redraw(untyped_factory)\n"
        "graph = m.Graph(list(nx.Graph().nodes), [])\n"
        "graph.copy()\n"
        "m.Graph(list(nx.Graph().nodes), []).vertices\n",
    )
    findings = "\n".join(typecheck.imprecise([example])[example.name])
    for source in ("m.always_redraw()", "m.Graph()", "Graph.copy()", "Graph.vertices"):
        assert f"(from {source})" in findings


def test_a_generic_class_keeps_its_inherited_methods() -> None:
    methods = typecheck._manimgx_methods()["Graph"]
    assert {"add_vertices", "copy"} <= set(methods)
    assert not {"add_node", "add_nodes_from"} & set(methods)


BOX = (
    "import manimgx as m\n"
    "class Box(m.Square):\n"
    "    def grow(self):\n"
    "        return self.scale(2)\n"
    "box = Box()\n"
)


def test_a_scenes_own_method_through_animate_is_not_an_escape() -> None:
    own = (
        BOX + "box.animate.grow()  # ty: ignore[unresolved-attribute]\n"
        "box.animate.shift(m.UP).grow()  # ty: ignore[unresolved-attribute]\n"
        "box.always.grow()  # ty: ignore[unresolved-attribute]\n"
    )
    assert typecheck.escapes(own.encode()) == []
    # a library's method, another rule, or the method itself: escapes
    others = (
        BOX + "box.animate.shfit(m.UP)  # ty: ignore[unresolved-attribute]\n"
        "box.animate.grow(1)  # ty: ignore[invalid-argument-type]\n"
        "box.grow()  # ty: ignore[unresolved-attribute]\n"
    )
    found = typecheck.escapes(others.encode())
    assert [line.split(":")[0] for line in found] == ["line 6", "line 7", "line 8"]


@pytest.mark.usefixtures("cases")
def test_a_scenes_own_method_through_animate_is_not_manimgxs_imprecision() -> None:
    example = made(
        "own", BOX + "box.animate.grow()  # ty: ignore[unresolved-attribute]\n"
    )
    assert typecheck.imprecise([example]) == {}
