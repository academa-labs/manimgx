"""A type checker knows each keyword a mobject or an animation takes, and each method
`.animate` and `.always` call, and nothing else.

- Every TypedDict that a signature unpacks (`**kwargs: Unpack[Style]`) is closed (PEP 728):
  a keyword it doesn't name is an error to a type checker, not a key of type `object`.
- So ty reports a misspelled keyword (`m.Circle(colour=…)`), where manimgx would ignore it,
  and a misspelled method through `.animate` or `.always` (`.animate.shfit(…)`), or in a
  function given to `.animate`, which manimgx reports only when the scene runs; it takes the
  methods there as the mobject's.
"""

import importlib
import re
import subprocess
import sys
from pathlib import Path

from typing_extensions import is_typeddict

PACKAGE = Path(__file__).parents[2] / "src" / "manimgx"


def unpacked() -> dict[str, set[str]]:
    """The TypedDicts that the package's signatures unpack, by module: their names."""
    found: dict[str, set[str]] = {}
    for path in PACKAGE.rglob("*.py"):
        names = set(re.findall(r"Unpack\[(\w+)", path.read_text(encoding="utf-8")))
        if names:
            module = ".".join(path.relative_to(PACKAGE.parent).with_suffix("").parts)
            found[module.removesuffix(".__init__")] = names
    return found


def test_every_typeddict_a_signature_unpacks_is_closed() -> None:
    seen = 0
    for module, names in unpacked().items():
        namespace = vars(importlib.import_module(module))
        for name in names:
            kind = namespace.get(name)
            # imported for the type checker only: checked where it is defined
            if kind is None:
                continue
            assert is_typeddict(kind), f"{module}.{name}"
            assert getattr(kind, "__closed__", False), f"{module}.{name} is open"
            seen += 1
    assert seen > 50


def _ty(scene: Path) -> dict[int, str]:
    """The rule ty breaks on each line of a scene, by line."""
    ty = Path(sys.executable).parent / "ty"
    done = subprocess.run(
        [
            str(ty),
            "check",
            "--python",
            sys.prefix,
            "--output-format",
            "concise",
            str(scene),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    found = re.findall(r"^\S+:(\d+):\d+: \w+\[([\w-]+)\]", done.stdout, re.MULTILINE)
    return {int(line): rule for line, rule in found}


def test_ty_reports_a_misspelling(tmp_path: Path) -> None:
    scene = tmp_path / "scene.py"
    scene.write_text(
        "import manimgx as m\n"
        "\n"
        "m.Circle(colour=m.BLUE)\n"
        'm.Text("x", font_szie=20)\n'
        "m.FadeIn(m.Dot(), run_tme=2)\n"
        "m.Square().set_style(fill_opactiy=1)\n"
        "m.Square().animate.shfit(m.RIGHT)\n"
        "m.Square().animate.shift(m.RIGHT).scael(2)\n"
        "m.Dot().always.nxt_to(m.ORIGIN)\n"
        "m.Square().animate(lambda s: s.shfit(m.RIGHT))\n",
        encoding="utf-8",
    )
    assert _ty(scene) == {
        3: "unknown-argument",
        4: "unknown-argument",
        5: "unknown-argument",
        6: "unknown-argument",
        7: "unresolved-attribute",
        8: "unresolved-attribute",
        9: "unresolved-attribute",
        10: "unresolved-attribute",
    }


def test_ty_takes_the_methods_through_animate_as_the_mobjects(tmp_path: Path) -> None:
    # a kind's own parameters, where they are its own
    scene = tmp_path / "scene.py"
    scene.write_text(
        "import manimgx as m\n"
        "\n"
        "m.Axes().animate.add_coordinates([1, 2])\n"
        "m.DecimalNumber(1).animate.increment_value(2)\n"
        'm.Text("x").animate.scale(2, about_edge=m.UP)\n'
        "m.Cone().animate.set_direction(m.UP)\n"
        "m.Square().animate.close_path().make_jagged()\n"
        "m.Dot().always.next_to(m.ORIGIN, m.UP)\n"
        "m.Square().animate(lambda s: s.shift(m.UP).set_color(m.RED))\n",
        encoding="utf-8",
    )
    assert _ty(scene) == {}
