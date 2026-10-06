"""Attribute process startup and reusable GPU work without changing any acceptance rule."""

import argparse
import dataclasses
import importlib
import json
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from pathlib import Path


def timed[T](name: str, action: Callable[[], T], timings: dict[str, float]) -> T:
    started = time.perf_counter()
    value = action()
    timings[name] = time.perf_counter() - started
    print(f"{name}: {timings[name]:.6f}s", flush=True)
    return value


def workload(scene: Path, output: Path) -> None:
    """Bound full CLI export, isolated authoring, and first/repeated native draws separately."""
    timings = {}
    failures = []
    programs = {
        "cli": [
            "-m",
            "manimgx",
            "render",
            str(scene),
            "--resolution",
            "64x36",
            "--fps",
            "5",
            "--output",
            str(output / "video.mp4"),
        ],
        "authoring": [
            "-c",
            """
    import json, sys, time
    from pathlib import Path
    import manimgx as m
    from manimgx.cli.scenes import scene
    started = time.perf_counter()
    kind = scene(Path(sys.argv[1]), None)
    m.config.pixel_width, m.config.pixel_height, m.config.frame_rate = 64, 36, 5
    with Path(sys.argv[2]).open('wb') as stream:
        film = kind().render(take=stream.write)
    print(json.dumps({'seconds': time.perf_counter() - started, 'frames': film.frame_count}), flush=True)
    """,
            str(scene),
            str(output / "recording.take"),
        ],
        "replay": [
            "-c",
            """
    import hashlib, json, sys, time
    from pathlib import Path
    from manimgx import _engine
    def measure(name, action):
        started = time.perf_counter()
        cpu_started = time.process_time()
        result = action()
        print(json.dumps({'phase': name, 'seconds': time.perf_counter() - started, 'cpu_seconds': time.process_time() - cpu_started}), flush=True)
        return result
    replay = measure('decode', lambda: _engine.Replay(Path(sys.argv[1]).read_bytes()))
    print(json.dumps(measure('device_and_eager_pipelines', _engine.adapter_info)), flush=True)
    for frame in dict.fromkeys([0, replay.frames // 2, replay.frames - 1]):
        first = measure(f'frame_{frame}_first', lambda: replay.render(frame))
        repeat = measure(f'frame_{frame}_repeat', lambda: replay.render(frame))
        assert first == repeat
        print(json.dumps({'frame': frame, 'sha256': hashlib.sha256(first).hexdigest()}), flush=True)
    expected = []
    for sweep in range(2):
        for shot, (frame, repeat) in enumerate(replay.timeline):
            started = time.perf_counter()
            cpu_started = time.process_time()
            pixels = replay.render(frame)
            seconds = time.perf_counter() - started
            cpu_seconds = time.process_time() - cpu_started
            digest = hashlib.sha256(pixels).hexdigest()
            if sweep == 0:
                expected.append(digest)
            else:
                assert digest == expected[shot]
            print(json.dumps({'sweep': sweep, 'frame': frame, 'repeat': repeat, 'seconds': seconds, 'cpu_seconds': cpu_seconds, 'sha256': digest}), flush=True)
    """,
            str(output / "recording.take"),
        ],
    }
    try:
        for phase, command in programs.items():
            if command[0] == "-c":
                command[1] = textwrap.dedent(command[1])
            started = time.perf_counter()
            with (output / f"{phase}.log").open("wb") as log:
                try:
                    subprocess.run(
                        [sys.executable, *command],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=300,
                        check=True,
                    )
                except (
                    subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                ) as error:
                    failures.append(f"{phase}: {error}")
                finally:
                    timings[phase] = time.perf_counter() - started
                    print(phase, timings[phase], flush=True)
    finally:
        (output / "timings.json").write_text(
            json.dumps({"seconds": timings, "failures": failures}, indent=2),
            encoding="utf-8",
        )
    if failures:
        raise RuntimeError("; ".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fresh", action="store_true")
    mode.add_argument("--workload", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.workload is not None:
        workload(args.workload.resolve(), output)
        return
    timings: dict[str, float] = {}
    runner = timed(
        "import_runner",
        lambda: importlib.import_module("tests.integration.corpus.run_manimgx"),
        timings,
    )
    # Imports stay after the measured cold import; this is a diagnostic entry point.
    from tests.integration.corpus import engines, probe
    from tests.integration.corpus.case import Case, Failure, frames_to_json

    import manimgx as m
    from manimgx import _engine
    from manimgx.config import Config, config
    from manimgx.rendering.feed import view

    case = Case("basic_usage")
    recorded = timed(
        "fresh_authoring",
        lambda: probe._call(
            "tests.integration.corpus.probe",
            [str(output), case.name, "--take"],
            case,
            output / "authoring.log",
        ),
        timings,
    )
    if not recorded:
        raise RuntimeError("fresh authoring failed; see authoring.log")
    take = (output / "recording.take").read_bytes()
    replay = timed("decode_take", lambda: _engine.Replay(take), timings)
    adapter = timed("device_and_eager_pipelines", _engine.adapter_info, timings)
    timed("adapter_warm", _engine.adapter_info, timings)
    player = timed("new_player", lambda: _engine.Player(64, 64), timings)
    uniform, _, _ = view(m.Scene().camera, 64, 64)
    empty = timed(
        "empty_draw_cold", lambda player=player: player.render(uniform, b""), timings
    )
    assert (
        timed(
            "empty_draw_warm",
            lambda player=player: player.render(uniform, b""),
            timings,
        )
        == empty
    )
    first = timed("replay_draw_first", lambda replay=replay: replay.render(0), timings)
    assert (
        timed("replay_draw_repeat", lambda replay=replay: replay.render(0), timings)
        == first
    )
    del player, replay

    names = [
        "basic_usage",
        "gradient_example",
        "text_ligature_colors_example",
        "three_d_light_source_position",
        "counterclockwise_path_example",
    ]
    defaults = {
        field.name: getattr(config, field.name) for field in dataclasses.fields(Config)
    }
    records = {}
    repeated = {}
    for index, name in enumerate(names + list(reversed(names))):
        for key, value in defaults.items():
            setattr(config, key, value)
        _, frames, count = timed(
            f"warm_scene_{index}_{name}",
            lambda name=name: runner.render(Case(name).scene, None, None),
            timings,
        )
        record = {
            "render": frames_to_json(frames),
            "duration_exact": str(frames.duration),
            "film_frames": count,
        }
        if name in records:
            repeated[name] = record == records[name]
        records[name] = record
    fresh = {}
    if args.fresh:
        for name in names:
            result = timed(
                f"fresh_scene_{name}",
                lambda name=name: engines.run(Case(name), "manimgx"),
                timings,
            )
            if isinstance(result.frames, Failure):
                raise RuntimeError(result.frames.error)
            # Archival JSON rounding is shared on both sides; exact duration is recorded too.
            fresh[name] = frames_to_json(result.frames) == records[name]["render"]
    (output / "startup.json").write_text(
        json.dumps(
            {
                "adapter": adapter,
                "package": m.__file__,
                "timings": timings,
                "warm_repeats_exact": repeated,
                "fresh_matches_warm": fresh,
                "records": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if not all(repeated.values()) or not all(fresh.values()):
        raise RuntimeError("process lifetime changed scene output; see startup.json")


if __name__ == "__main__":
    main()
