"""The trees the timed benchmarks compare and their rounds, from `--bench` and `--bench-rounds`
(declared in `tests/conftest.py`), and the table a timed run ends with: on the terminal, and in
the job's summary on GitHub Actions."""

import os

import pytest
from tests.benchmarks.harness import Row, Tree, checkout, here

LABELS = pytest.StashKey[tuple[str, str]]()
HEADER = ("workload", "base", "head", "change", "rounds", "wall", "memory", "work")


@pytest.fixture(scope="session")
def trees(pytestconfig: pytest.Config) -> tuple[Tree, Tree] | None:
    """(the tree compared with, this checkout) with `--bench REF`, None without: the suite.
    A commit's tree is made in pytest's cache, and kept."""
    ref = pytestconfig.getoption("bench")
    if ref is None:
        return None
    base = checkout(str(ref), pytestconfig.cache.mkdir("manimgx-trees"))
    head = here()
    pytestconfig.stash[LABELS] = (base.label, head.label)
    return base, head


@pytest.fixture(scope="session")
def rounds(pytestconfig: pytest.Config) -> int:
    value = pytestconfig.getoption("bench_rounds")
    assert isinstance(value, int)
    return value


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    rows = sorted(
        (
            value
            for reports in terminalreporter.stats.values()
            for report in reports
            if getattr(report, "when", None) == "call"
            for name, value in getattr(report, "user_properties", ())
            if name == "timed" and isinstance(value, Row)
        ),
        key=lambda row: row.order,
    )
    if not rows:
        return
    base, head = config.stash.get(LABELS, ("REF", "this checkout"))
    rounds = config.getoption("bench_rounds")
    title = f"{head} against {base}: {rows[0].unit}, the median of {rounds} rounds"
    table = [HEADER, *(row.cells for row in rows)]
    widths = [max(len(row[k]) for row in table) for k in range(len(HEADER))]
    terminalreporter.section(f"benchmarks: {title}")
    for row in table:
        cells = [
            cell.ljust(width) if k in (0, len(row) - 1) else cell.rjust(width)
            for k, (cell, width) in enumerate(zip(row, widths, strict=True))
        ]
        terminalreporter.write_line("  ".join(cells).rstrip())
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(f"### Benchmarks: {title}\n\n")
            for k, row in enumerate(table):
                out.write("| " + " | ".join(row) + " |\n")
                if k == 0:
                    out.write("|" + "---|" * len(HEADER) + "\n")
            out.write("\n")
