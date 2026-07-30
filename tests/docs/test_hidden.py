"""No example teaches a name manimgx hides (`@deprecated`): not the pages', the README's, the
docstrings' nor the example films' (`examples/`, which the Gallery shows). ty checks each with
`deprecated` an error. The example of a hidden object's own docstring is not shown, and is
not checked."""

import ast
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@cache
def hidden_spans(path: Path) -> list[tuple[int, int]]:
    """The lines of each definition a module decorates with `@deprecated`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
        and any("deprecated" in ast.unparse(d) for d in node.decorator_list)
    ]


def shown(where: str) -> bool:
    """Whether an example is shown: one on a page, or in the docstring of what isn't hidden."""
    file, _, line = where.rpartition(":")
    path = ROOT / file
    if not file.startswith("src/"):
        return True
    return not any(a <= int(line) <= b for a, b in hidden_spans(path))


def test_no_example_uses_a_hidden_name(tmp_path: Path) -> None:
    pytest.importorskip("markdown")  # the docs group's, which docs.examples imports
    from docs import examples

    for n, example in enumerate(examples.examples()):
        if shown(example.where):
            (tmp_path / f"example_{n}.py").write_text(
                f"# {example.where}\n{example.code}", encoding="utf-8"
            )
    for film in sorted((ROOT / "examples").glob("*.py")):
        (tmp_path / f"film_{film.name}").write_text(
            f"# examples/{film.name}\n{film.read_text(encoding='utf-8')}",
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
            "--error",
            "deprecated",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    uses = []
    for line in done.stdout.splitlines():
        if "[deprecated]" in line:
            file, number = line.split(":")[:2]
            source = (tmp_path / Path(file).name).read_text(encoding="utf-8")
            uses.append(
                f"{source.splitlines()[0][2:]} (+{number}): {line.split('] ', 1)[1]}"
            )
    assert not uses, "examples that use a hidden name:\n" + "\n".join(uses)
