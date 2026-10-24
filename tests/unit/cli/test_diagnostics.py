"""Layout checks describe visible conflicts, including overlapping copies during transforms."""

import pytest

import manimgx as m
from manimgx.cli.diagnostics import at, view


@pytest.mark.parametrize("shift", [0, 0.0004, 0.1])
def test_a_text_copy_only_overlaps_when_it_moves_away(shift: float) -> None:
    scene = m.Scene()
    text = m.Text("A readable label")
    scene.add(text, text.copy().shift(shift * m.RIGHT))
    overlaps = [p for p in at(view(scene)) if p.kind == "overlap"]
    assert len(overlaps) == (shift >= 0.01)


@pytest.mark.parametrize("visible", [False, True])
def test_only_a_visible_line_crosses_a_label(visible: bool) -> None:
    scene = m.Scene()
    scene.add(
        m.Text("A readable label"),
        m.Line(m.LEFT, m.RIGHT, stroke_opacity=float(visible)),
    )
    crossings = [p for p in at(view(scene)) if p.kind == "crossing"]
    assert len(crossings) == visible
