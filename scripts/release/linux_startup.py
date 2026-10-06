"""Temporary, bounded attribution of the release wheel's Linux smoke hang."""

import argparse
import contextlib
import faulthandler
import io
import json
import os
import runpy
import signal
import subprocess
import sys
import time
import wave
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def phase(name: str) -> Iterator[None]:
    print(json.dumps({"phase": name, "event": "start"}), flush=True)
    start = time.perf_counter()
    yield
    print(
        json.dumps(
            {"phase": name, "event": "end", "seconds": time.perf_counter() - start}
        ),
        flush=True,
    )


def pipeline(output: Path, project: Path) -> None:
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    with phase("import"):
        import numpy as np

        import manimgx as m
        from manimgx import _engine
        from manimgx.rendering.feed import view

    with phase("wav_decode"):
        pcm = io.BytesIO()
        with wave.open(pcm, "wb") as stream:
            stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            stream.writeframes(bytes(9600))
        assert m.Sound(pcm.getvalue()).samples.shape == (4800, 1)
    with phase("opus_decode"):
        opus = m.Sound((project / "rust/ffmpeg/tests/silence.opus").read_bytes())
        assert opus.samples.shape == (960, 1)
        assert np.isfinite(opus.samples).all()
    with phase("typeset"):
        m.Text("manimgx")
    m.config.pixel_width, m.config.pixel_height = 320, 180
    m.config.frame_rate = 60
    with phase("authoring_without_gpu"):
        script = runpy.run_path(str(project / "scripts/release/smoke_test.py"))
        namespace: dict[str, object] = {}
        exec(script["scene_source"](), namespace)
        scene = namespace["Smoke"]
        chunks: list[bytes] = []
        film = scene().render(take=chunks.append)  # ty: ignore[call-non-callable]
        take = b"".join(chunks)
        (output / "smoke.take").write_bytes(take)
        print(f"authored {film.frame_count} frames", flush=True)
    with phase("take_decode"):
        replay = _engine.Replay(take)
    with phase("device_and_eager_pipelines"):
        print(_engine.adapter_info(), flush=True)
    with phase("empty_draw"):
        player = _engine.Player(320, 180)
        uniform, _, _ = view(m.Scene().camera, 320, 180)
        player.render(uniform, b"")
    with phase("text_draw_first"):
        replay.render(film.frame_count // 2)
    with phase("text_draw_warm"):
        replay.render(film.frame_count // 2)
    with phase("render_and_encode"):
        path = output / "Smoke.mp4"
        scene().render(path)  # ty: ignore[call-non-callable]
    with phase("aac_decode"):
        assert np.any(m.Sound(path).samples)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("project", type=Path)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    output, project = args.output.resolve(), args.project.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.child:
        pipeline(output, project)
        return
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        str(output),
        str(project),
        "--child",
    ]
    with (output / "phases.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            code = child.wait(timeout=120)
        except subprocess.TimeoutExpired:
            os.kill(child.pid, signal.SIGUSR1)
            (output / "maps.txt").write_text(
                Path(f"/proc/{child.pid}/maps").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with (output / "threads.txt").open("w", encoding="utf-8") as threads:
                subprocess.run(
                    [
                        "ps",
                        "-L",
                        "-p",
                        str(child.pid),
                        "-o",
                        "pid,tid,pcpu,stat,wchan,comm",
                    ],
                    stdout=threads,
                    check=False,
                )
            with (output / "native-stack.txt").open("w", encoding="utf-8") as stack:
                try:
                    subprocess.run(
                        [
                            "gdb",
                            "--batch",
                            "-p",
                            str(child.pid),
                            "-ex",
                            "set pagination off",
                            "-ex",
                            "thread apply all bt 30",
                        ],
                        stdout=stack,
                        stderr=subprocess.STDOUT,
                        timeout=30,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    stack.write("gdb exceeded its diagnostic budget\n")
            code = 124
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
    print((output / "phases.log").read_text(encoding="utf-8"), flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
