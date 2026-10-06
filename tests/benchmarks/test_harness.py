"""Benchmark subprocesses use the same package as their parent, wherever it is installed."""

import subprocess
import sys
from pathlib import Path

import pytest
from tests.benchmarks import harness

import manimgx


@pytest.mark.parametrize("location", ["checkout/src", "venv/site-packages"])
def test_children_use_the_imported_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    package = tmp_path / location / "manimgx"
    package.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_text("", encoding="utf-8")
    monkeypatch.setattr(manimgx, "__file__", str(init))
    child = subprocess.run(
        [sys.executable, "-c", "import manimgx; print(manimgx.__file__)"],
        env=harness._environment(harness.here(), str(tmp_path)),
        capture_output=True,
        text=True,
        check=True,
    )
    assert Path(child.stdout.strip()).resolve() == init.resolve()
