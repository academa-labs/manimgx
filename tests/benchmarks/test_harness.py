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


@pytest.mark.parametrize("finish", ["deadline", "caller_error", "success"])
def test_a_render_process_is_reaped_on_every_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finish: str
) -> None:
    popen = subprocess.Popen
    children: list[subprocess.Popen[str]] = []

    def spawn(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        # Exercise an actual process without paying for a render to test supervision.
        code = "pass" if finish == "success" else "import time; time.sleep(60)"
        child = popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        children.append(child)
        return child

    monkeypatch.setattr(harness.subprocess, "Popen", spawn)
    monkeypatch.setattr(harness, "TIMEOUT", 0.1 if finish == "deadline" else 30)
    context = harness._launch(
        harness.Tree(tmp_path, "test package"),
        harness.Workload(tmp_path / "scene.py"),
        str(tmp_path),
        subprocess.PIPE,
    )
    if finish == "deadline":
        with (
            pytest.raises(RuntimeError, match=r"timed out rendering scene\.py"),
            context as child,
        ):
            child.communicate()
    elif finish == "caller_error":
        with pytest.raises(ValueError, match="caller failed"), context:
            raise ValueError("caller failed")
    else:
        with context as child:
            child.communicate()
        assert child.returncode == 0
    assert len(children) == 1
    assert children[0].poll() is not None
