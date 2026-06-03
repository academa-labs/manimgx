"""Render scenes with manimgx in this process, reading every frame back from the player.

    python -m tests.integration.corpus.run_manimgx SCENE --out RESULT [--video OUT.mkv] [--mp4]

One scene per process: a scene rendered after another can differ (the engine may leak state
between scenes), so references and checks render each scene alone. `--mp4` also sends the
scene through the product's exporter and counts the frames of the MP4 it writes. `--sequence`
renders several scenes in one process, in order, to find exactly such leaks.
"""

import argparse
import dataclasses
import json
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import av
from tests.integration.corpus.case import FPS, SIZE, Frames, Json
from tests.integration.corpus.frames import Recorder, rgb
from tests.integration.corpus.runtime import load, seed, the_scene, write_result

import manimgx
from manimgx.config import Config, config


def render(
    scene_path: Path, video: Path | None, mp4: Path | None
) -> tuple[bytes, Frames, int]:
    """(source, frames, frame count of the film)."""
    source = scene_path.read_bytes()
    seed()
    config.pixel_width, config.pixel_height = SIZE
    config.frame_rate = FPS
    module = load(scene_path, source, f"corpus_scene_{scene_path.parent.name}")
    scene = the_scene(module, manimgx.Scene)()
    recorder = Recorder(SIZE, FPS, video)
    film = scene.render(
        mp4, frames=lambda frame: recorder.add(rgb(frame.pixels(), SIZE), frame.repeat)
    )
    runs = recorder.close()
    frames = Frames(
        runs=runs, duration=scene.clock, timeline=((Fraction(0), recorder.count),)
    )
    return source, frames, film.frame_count


def mp4_frames(path: Path) -> int:
    """How many frames an MP4 shows at the corpus rate: its samples' durations (a held frame is
    one sample that lasts), every sample decoded."""
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        durations, decoded = [], 0
        for packet in container.demux(stream):
            if packet.size:  # the last packet, empty, drains the decoder
                durations.append(packet.duration or 0)
            decoded += len(packet.decode())
        time_base = stream.time_base
    if decoded != len(durations):
        msg = f"{path}: {decoded} of its {len(durations)} samples decode"
        raise ValueError(msg)
    assert time_base is not None
    shown = time_base * sum(durations) * FPS
    if shown.denominator != 1:
        msg = f"{path} lasts {shown} frames"
        raise ValueError(msg)
    return int(shown)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--mp4", action="store_true")
    parser.add_argument("--sequence", action="store_true")
    args = parser.parse_args()

    if args.sequence:
        # each scene starts from the same config: only the engine's own state may carry over
        defaults = {f.name: getattr(config, f.name) for f in dataclasses.fields(Config)}
        results: dict[str, Json] = {}
        for path in args.scene:
            for name, value in defaults.items():
                setattr(config, name, value)
            _, frames, _ = render(path, None, None)
            results[path.parent.name] = [[h, n] for h, n in frames.runs]
        args.out.write_text(json.dumps(results), encoding="utf-8")
        return

    (scene_path,) = args.scene
    extra: dict[str, Json] = {}
    with tempfile.TemporaryDirectory() as tmp:
        mp4 = Path(tmp) / "product.mp4" if args.mp4 else None
        source, frames, film_frames = render(scene_path, args.video, mp4)
        if mp4 is not None:
            extra = {"film_frames": film_frames, "mp4_frames": mp4_frames(mp4)}
    if "manim" in sys.modules:
        msg = "the scene imported Manim CE; a manimgx render must not"
        raise RuntimeError(msg)
    write_result(args.out, source, frames, extra)


if __name__ == "__main__":
    main()
