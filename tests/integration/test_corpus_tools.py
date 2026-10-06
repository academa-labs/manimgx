"""The corpus's tools hold to their rules.

- A stored manimgx film is a baseline whatever CE did and however the case was reviewed:
  `test_regression` fails exactly when today's film differs from it (its frames, duration or
  timeline), and never skips; a difference of timing alone is explained without rendering.
- A type report's imprecision is manimgx's: an untyped value from another package is not
  manimgx's output, but manimgx's outputs stay imprecise however untyped their inputs, each
  named by the call or attribute it comes from (a generic class's inherited methods too).
- A type report's escapes are the scene's: every suppression is one, but for a method of the
  scene's own class called through `.animate` or `.always`, which manimgx's types can't name
  (nor is its type manimgx's imprecision).
"""

import json
import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from tests.integration import test_corpus as corpus
from tests.integration.corpus import case, engines, typecheck
from tests.integration.corpus.case import (
    FPS,
    METRICS,
    SIZE,
    Case,
    Comparison,
    Engine,
    Facts,
    Failure,
    Frames,
)

STORED = Frames((("before", 2),), Fraction(1, 5), ((Fraction(0), 2),))
CHANGES = {
    "same": STORED,
    "pixels": replace(STORED, runs=(("after", 2),)),
    "duration": replace(STORED, duration=Fraction(3, 10)),
    "timeline": replace(STORED, timeline=((Fraction(1, 10), 2),)),
}


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
@pytest.mark.parametrize("ce", ["same", "different", "failure"])
@pytest.mark.parametrize("change", CHANGES)
def test_a_stored_film_holds_whatever_ce_did(
    ce: str, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = made("baseline", "import manimgx\n")
    theirs = {"same": STORED, "different": replace(STORED, runs=(("ce", 2),))}
    error = 0.0 if ce == "same" else 255.0
    compared = Comparison(((0, 0, (error,) * len(METRICS)),), ())
    ce_render = theirs.get(ce, Failure("CE cannot render this scene"))
    facts = Facts(example.source_hash(), SIZE, FPS, STORED, ce_render, "", compared)
    example.write_facts(facts)
    assert example.state(corpus.SETTINGS) == (
        "working" if ce == "same" else "not_matching"
    )

    def render(
        _: Case, engine: Engine, *, video: Path | None = None, mp4: bool = False
    ) -> engines.Result:
        assert (engine, video, mp4) == ("manimgx", None, True)
        return engines.Result(
            example.source_hash(), CHANGES[change], film_frames=2, mp4_frames=2
        )

    monkeypatch.setattr(engines, "run", render)
    monkeypatch.setattr(corpus, "_explain", lambda *_: "the stored film changed")
    try:
        if change == "same":
            corpus.test_regression(example)
        else:
            with pytest.raises(pytest.fail.Exception, match="the stored film changed"):
                corpus.test_regression(example)
    except pytest.skip.Exception as skipped:
        pytest.fail(f"a stored baseline cannot be skipped: {skipped}", pytrace=False)


@pytest.mark.parametrize("change", ["duration", "timeline"])
def test_a_change_of_timing_alone_is_explained_without_rendering(
    change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def render(*_: object, **__: object) -> engines.Result:
        pytest.fail("timing diagnostics should not render or decode unchanged pixels")

    monkeypatch.setattr(engines, "run", render)
    message = corpus._explain(Case("timing"), STORED, CHANGES[change])
    said = {
        "duration": ("3/10s", "1/5s"),
        "timeline": ("Fraction(1, 10)", "Fraction(0, 1)"),
    }
    assert all(part in message for part in (change, "instead of", *said[change]))


@pytest.mark.usefixtures("cases")
@pytest.mark.parametrize("repeatable", [True, False])
def test_diagnostics_keep_actual_frames_without_a_local_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repeatable: bool
) -> None:
    example = made("changed", "import manimgx\n")
    output = tmp_path / "diagnostics"
    monkeypatch.setattr(corpus, "DIFFS", output)
    fresh = CHANGES["pixels"]
    repeated = fresh if repeatable else STORED

    def render(
        _: Case, engine: Engine, *, video: Path | None = None, mp4: bool = False
    ) -> engines.Result:
        assert engine == "manimgx"
        assert video is not None
        assert not mp4
        video.write_bytes(b"actual rendered film")
        return engines.Result(example.source_hash(), repeated)

    monkeypatch.setattr(engines, "run", render)
    message = corpus._explain(example, STORED, fresh)
    assert (output / example.name / "fresh.mkv").read_bytes() == b"actual rendered film"
    recorded = json.loads(
        (output / example.name / "frames.json").read_text(encoding="utf-8")
    )
    assert case.frames_from_json(recorded) == repeated
    assert ("a second render differs" in message) != repeatable


@pytest.mark.usefixtures("cases")
def test_diagnostics_inspect_the_whole_film(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = made("long_film", "import manimgx\n")
    example.video("manimgx").touch()
    monkeypatch.setattr(corpus, "DIFFS", tmp_path / "diagnostics")
    expected = replace(STORED, runs=(("before", 202),))
    fresh = replace(expected, runs=(("after", 202),))
    monkeypatch.setattr(
        engines, "run", lambda *_, **__: engines.Result(example.source_hash(), fresh)
    )

    def decode(path: Path, _: tuple[int, int]):
        for i in range(202):
            value = 0 if path == example.video("manimgx") else 255 if i == 201 else 1
            yield np.full((7, 7, 3), value, dtype=np.uint8)

    monkeypatch.setattr(corpus, "decode", decode)
    message = corpus._explain(example, expected, fresh)
    assert "largest change 255.0" in message
    assert "at frame 201" in message
    assert (
        tmp_path / "diagnostics" / example.name / "reference_vs_today_0201.png"
    ).is_file()


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
