"""A type checker knows each keyword a mobject or an animation takes, and nothing else.

- Every TypedDict that a signature unpacks (`**kwargs: Unpack[Style]`) is closed (PEP 728):
  a keyword it doesn't name is an error to a type checker, not a key of type `object`.
- So ty reports a misspelled keyword (`m.Circle(colour=…)`), where manimgx would ignore it.
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


def test_ty_reports_a_misspelled_keyword(tmp_path: Path) -> None:
    scene = tmp_path / "scene.py"
    scene.write_text(
        "import manimgx as m\n"
        "\n"
        "m.Circle(colour=m.BLUE)\n"
        'm.Text("x", font_szie=20)\n'
        "m.FadeIn(m.Dot(), run_tme=2)\n"
        "m.Square().set_style(fill_opactiy=1)\n",
        encoding="utf-8",
    )
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
    flagged = {
        int(line.split(":")[1])
        for line in done.stdout.splitlines()
        if "[unknown-argument]" in line
    }
    assert flagged == {3, 4, 5, 6}, done.stdout
