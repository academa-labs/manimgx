"""Attribute process startup and reusable GPU work without changing any acceptance rule."""

import argparse
import dataclasses
import importlib
import json
import time
from collections.abc import Callable
from pathlib import Path


def timed[T](name: str, action: Callable[[], T], timings: dict[str, float]) -> T:
    started = time.perf_counter()
    value = action()
    timings[name] = time.perf_counter() - started
    print(f"{name}: {timings[name]:.6f}s", flush=True)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
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
