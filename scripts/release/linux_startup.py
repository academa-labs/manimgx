"""Temporary, bounded attribution of the release wheel's Linux smoke hang."""

import argparse
import contextlib
import faulthandler
import hashlib
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


def pipeline(output: Path, project: Path, case: str) -> None:
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    with phase("import"):
        import numpy as np

        import manimgx as m
        from manimgx import _engine
        from manimgx.rendering.feed import view

    m.config.pixel_width, m.config.pixel_height = 320, 180
    m.config.frame_rate = 60
    if case != "smoke":
        with phase("authoring_without_gpu"):
            scene = m.Scene()
            match case:
                case "square":
                    scene.add(m.Square(fill_opacity=1, stroke_width=0))
                case "line":
                    scene.add(m.Line())
                case "text":
                    scene.add(m.Text("manimgx"))
                case "glyph":
                    scene.add(m.Text("m"))
            scene.wait(0.1)
            chunks: list[bytes] = []
            film = scene.render(take=chunks.append)
            take = b"".join(chunks)
            (output / "smoke.take").write_bytes(take)
        with phase("device_and_eager_pipelines"):
            print(_engine.adapter_info(), flush=True)
        with phase("first_draw"):
            replay = _engine.Replay(take)
            first = replay.render(0)
        (output / "first.rgba").write_bytes(first)
        print(
            json.dumps(
                {"size": replay.size, "rgba_sha256": hashlib.sha256(first).hexdigest()}
            ),
            flush=True,
        )
        with phase("warm_draw"):
            repeated = replay.render(0)
        (output / "warm.rgba").write_bytes(repeated)
        if first != repeated:
            raise RuntimeError("cold and warm draws differ; retained both RGBA frames")
        return
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
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument(
        "--case", choices=("smoke", "square", "line", "text", "glyph"), default="smoke"
    )
    args = parser.parse_args()
    output, project = args.output.resolve(), args.project.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.child:
        pipeline(output, project, args.case)
        return
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        str(output),
        str(project),
        "--child",
        "--case",
        args.case,
    ]
    with (output / "phases.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            code = child.wait(timeout=args.timeout)
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
            # Reattach after the program runs between samples: a fixed PC, loop or
            # changing long computation must be distinguished from compiler work.
            debug = output / "sample.gdb"
            debug.write_text(
                "set pagination off\nthread apply all bt 30\n"
                "python\n"
                "import gdb, os\n"
                "maps = []\n"
                "constants = []\n"
                "for line in open('/proc/%s/maps' % gdb.selected_inferior().pid):\n"
                "    parts = line.split()\n"
                "    if 'x' in parts[1] and len(parts) == 5:\n"
                "        maps.append(tuple(int(v, 16) for v in parts[0].split('-')))\n"
                "    if parts[1] == 'r--p' and len(parts) == 5:\n"
                "        constants.append(tuple(int(v, 16) for v in parts[0].split('-')))\n"
                "for start, end in constants:\n"
                "    print('ANONYMOUS CONSTANT SECTION', hex(start), hex(end))\n"
                "    gdb.execute('x/%dwx %s' % ((end-start)//4, start))\n"
                "for thread in gdb.selected_inferior().threads():\n"
                "    thread.switch()\n"
                "    pc = int(gdb.parse_and_eval('$pc'))\n"
                "    for start, end in maps:\n"
                "        if start <= pc < end:\n"
                "            print('ACTIVE JIT THREAD', thread.num, hex(pc), hex(start), hex(end))\n"
                "            gdb.execute('info symbol $pc')\n"
                "            gdb.execute('info all-registers')\n"
                "            try:\n"
                "                gdb.execute('x/4096wx $rsp')\n"
                "            except gdb.error as error:\n"
                "                print(error)\n"
                "            gdb.execute('x/100i $pc-128')\n"
                "            gdb.execute('disassemble /r %s,%s' % (start, end))\n"
                "end\ndetach\n",
                encoding="utf-8",
            )
            for sample in range(2):
                if sample:
                    time.sleep(3)
                with (output / f"native-stack-{sample}.txt").open(
                    "w", encoding="utf-8"
                ) as stack:
                    try:
                        subprocess.run(
                            ["gdb", "--batch", "-p", str(child.pid), "-x", str(debug)],
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
