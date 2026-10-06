"""Bounded docs-render diagnostics using an already built wheel; writes timing evidence.

This manual experiment separates native startup, steady GPU readback, video encoding,
scene evaluation, and contention between independent processes. It does not accept or
rewrite corpus references, render a whole gallery, or use the documentation media cache.
"""

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

SIZE, FPS = (1280, 720), 60


def measure(name: str, output: Path, count: int) -> dict[str, object]:
    """One task in a fresh process, so cold timing includes a fresh native runtime."""
    started = time.perf_counter()
    try:
        import manimgx as m
        from manimgx import _engine
        from manimgx.rendering.feed import Feeder
        from manimgx.rendering.film import Cut, Frame

        m.config.pixel_width, m.config.pixel_height = SIZE
        m.config.frame_rate = FPS
        imported = time.perf_counter()
        result: dict[str, object] = {
            "task": name,
            "size": SIZE,
            "fps": FPS,
            "import_seconds": imported - started,
            "engine": _engine.__file__,
        }
        if name.startswith("scene-"):
            from docs.examples import Example, load

            source = Path("examples") / f"{name.removeprefix('scene-')}.py"
            result["scene_source_sha256"] = hashlib.sha256(
                source.read_bytes()
            ).hexdigest()
            scene = load(Example(source.read_text(), source.as_posix()))
            samples: list[float] = []
            indices: list[int] = []
            digest = hashlib.sha256()

            def keep(frame: Frame) -> None:
                # Eight seconds into both clips, their main geometry is visible. Evaluate
                # earlier frames without drawing them, then stop after this bounded sample.
                if frame.index < 8 * FPS:
                    return
                before = time.perf_counter()
                pixels = frame.pixels()
                samples.append(time.perf_counter() - before)
                indices.append(frame.index)
                assert len(pixels) == SIZE[0] * SIZE[1] * 4
                digest.update(pixels)
                if len(samples) == count:
                    raise Cut

            scene().render(frames=keep)
            assert len(samples) == count, (name, len(samples))
            result |= {
                "frame_indices": indices,
                "draw_seconds": samples,
                "rgba_sha256": digest.hexdigest(),
                "evaluation_and_draw_seconds": time.perf_counter() - imported,
            }
        else:
            kind = name.split("-", 1)[0]
            camera = m.Camera(three_d=kind == "mesh", phi=0.5, theta=-1.2)
            objects: list[m.Mobject]
            if kind == "mesh":
                objects = [m.Sphere(radius=1.8, resolution=(48, 24), color=m.BLUE)]
            else:
                objects = [
                    m.Circle(
                        radius=1.4,
                        color=m.BLUE if index % 2 else m.RED,
                        fill_opacity=0.4 if kind == "layers" else 1,
                        stroke_width=3,
                    ).shift(((index % 4 - 1.5) * 0.7, (index // 4 - 1) * 0.6, 0))
                    for index in range(12 if kind == "layers" else 1)
                ]
            player = _engine.Player(*SIZE)
            feeder = Feeder(*SIZE, player)
            view = feeder.frame(camera, objects)
            before = time.perf_counter()
            pixels = player.render(*view)
            result["cold_render_seconds"] = time.perf_counter() - before
            durations = []
            for _ in range(count):
                before = time.perf_counter()
                pixels = player.render(*view)
                durations.append(time.perf_counter() - before)
            result["warm_render_seconds"] = durations
            result["rgba_sha256"] = hashlib.sha256(pixels).hexdigest()
            assert len(pixels) == SIZE[0] * SIZE[1] * 4
            before = time.perf_counter()
            video = output / f"{name}.mp4"
            player.begin_export(str(video), FPS, "slow", 28)
            for _ in range(count):
                for obj in objects:
                    obj.shift((0.03, 0, 0))
                v, records, cameras = feeder.frame(camera, objects)
                player.push(v, records, cameras=cameras)
            result["encoder_stats"] = player.end_export()
            result["render_and_encode_seconds"] = time.perf_counter() - before
            result["video_bytes"] = video.stat().st_size
        result["process_seconds"] = time.perf_counter() - started
    except BaseException:
        result = {"task": name, "error": traceback.format_exc()}
    (output / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    return result


def main(output: Path, count: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "python": sys.version,
        "commit": os.environ.get("GITHUB_SHA"),
        "wheel_run": os.environ.get("WHEEL_RUN"),
    }
    failed = False
    for label, jobs, names in [
        ("serial", 1, ["solid", "layers", "mesh"]),
        ("concurrent", 2, ["layers-a", "layers-b"]),
        ("docs", 1, ["scene-catenoid_helicoid", "scene-harmonic_drive"]),
    ]:
        before = time.perf_counter()
        with ProcessPoolExecutor(
            max_workers=jobs, max_tasks_per_child=1, mp_context=get_context("spawn")
        ) as pool:
            results = [
                f.result()
                for f in [pool.submit(measure, name, output, count) for name in names]
            ]
        report[label] = {"wall_seconds": time.perf_counter() - before, "tasks": results}
        failed |= any("error" in result for result in results)
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frames", type=int, default=12)
    args = parser.parse_args()
    main(args.output.resolve(), args.frames)
