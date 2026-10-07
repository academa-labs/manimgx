"""Process isolation, video validation, aggregation and chart scaling."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scripts.benchmark import chart, run
from scripts.benchmark.scenes.suite_data import ring_pose


def test_unsupported_cpu_accounting_never_starts_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(run.os, "wait4", raising=False)
    monkeypatch.setattr(run, "command", lambda *args: [sys.executable, "-c", "pass"])

    def launch(*args: object, **kwargs: object) -> None:
        pytest.fail("the unsupported benchmark started a process")

    monkeypatch.setattr(run.subprocess, "Popen", launch)
    with pytest.raises(RuntimeError, match="macOS and Linux"):
        run.run_one(
            "manimgx",
            "linked_rings",
            1,
            argparse.Namespace(out=tmp_path, dry_run=False),
        )


@pytest.mark.skipif(
    not hasattr(run.os, "wait4"), reason="CPU timing runs on macOS and Linux"
)
@pytest.mark.parametrize("timeout", [False, True])
def test_unsuccessful_processes_are_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout: bool
) -> None:
    code = (
        "import time; print('started', flush=True); time.sleep(30)"
        if timeout
        else "import sys; print('failed deliberately', flush=True); sys.exit(7)"
    )
    monkeypatch.setattr(run, "command", lambda *args: [sys.executable, "-c", code])
    args = argparse.Namespace(out=tmp_path, timeout=0.5, dry_run=False)
    result = run.run_one("manimgx", "linked_rings", 1, args)
    assert result.status == ("timeout" if timeout else "failed")
    assert result.wall_seconds < 5
    assert not result.video
    assert Path(result.log).exists()
    assert ("started" if timeout else "failed deliberately") in result.error


def test_a_run_never_overwrites_an_existing_run(tmp_path: Path) -> None:
    folder = tmp_path / "linked_rings/manimgx/1"
    folder.mkdir(parents=True)
    marker = folder / "retained.txt"
    marker.write_text("measurement", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run.run_one("manimgx", "linked_rings", 1, argparse.Namespace(out=tmp_path))
    assert marker.read_text(encoding="utf-8") == "measurement"


@pytest.mark.parametrize("tool", run.TOOLS)
def test_encoder_options_must_match_fastest_preset_and_crf23(
    tmp_path: Path, tool: str
) -> None:
    path = tmp_path / "out.mp4"
    options = (
        "crf=23.0 subme=1 me=dia bframes=0"
        if tool.startswith("blender_")
        else "crf=23.0 cabac=0 subme=0 bframes=0"
    )
    path.write_bytes(f"x264 - core 165 - options: {options}\x00".encode())
    assert "crf=23.0" in run.encoder_evidence(path, tool)
    path.write_bytes(path.read_bytes().replace(b"crf=23.0", b"crf=18.0"))
    with pytest.raises(ValueError, match="Unexpected encoder"):
        run.encoder_evidence(path, tool)


def test_only_gx_can_use_explicit_cli_encoding_evidence(tmp_path: Path) -> None:
    path = tmp_path / "out.mp4"
    path.write_bytes(b"no x264 options")
    assert "Explicit ultrafast" in run.encoder_evidence(path, "manimgx")
    for tool in run.TOOLS[1:]:
        with pytest.raises(ValueError, match="Unexpected encoder"):
            run.encoder_evidence(path, tool)


def test_totals_require_every_scene_and_repeat() -> None:
    samples = [
        run.Run("orbit", "manimgx", i, [], status="complete", wall_seconds=value)
        for i, value in enumerate((1, 3), 1)
    ]
    result = run.summarize(samples, ["orbit", "linked_rings"], {"manimgx": 2})
    assert not result["complete"]
    assert result["totals"] == {}
    samples += [
        run.Run("linked_rings", "manimgx", i, [], status="complete", wall_seconds=value)
        for i, value in enumerate((2, 8), 1)
    ]
    assert run.summarize(samples, ["orbit", "linked_rings"], {"manimgx": 2})[
        "totals"
    ] == {"manimgx": 7}
    samples[-1].status = "invalid"
    assert not run.summarize(samples, ["orbit", "linked_rings"], {"manimgx": 2})[
        "complete"
    ]


def test_recorded_totals_match_every_run() -> None:
    data = json.loads((run.HERE / "results.json").read_text(encoding="utf-8"))
    rows = [
        run.Run(
            r["scene"],
            r["tool"],
            r["repeat"],
            [],
            status=r["status"],
            wall_seconds=r["wall_seconds"],
        )
        for r in data["runs"]
    ]
    result = run.summarize(rows, list(run.DURATIONS), run.REPEATS)
    assert len(rows) == 45
    assert result["complete"]
    assert result["totals"] == data["totals"]
    assert result["per_scene"] == data["per_scene"]


def test_normalized_chart_preserves_ratios() -> None:
    totals = {"manimgx": 2.0, "manimgl": 10.0, "manim_ce": 20.0}
    rows = chart.normalized_rows(totals)
    assert rows == [("ManimGX", 1), ("ManimGL", 5), ("ManimCE", 10)]
    assert (
        chart.normalized_rows({tool: seconds * 10 for tool, seconds in totals.items()})
        == rows
    )


@pytest.mark.parametrize("t", [0, 0.75, 1.5, 2.25, 3])
def test_ring_poses_remain_rigid(t: float) -> None:
    for i in range(8):
        rotation, position = ring_pose(i, t)
        np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
        assert np.linalg.det(rotation) == pytest.approx(1)
        assert np.isfinite(position).all()
