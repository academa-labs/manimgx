"""Compare fresh scenes with reviewed takes interpreted by a frozen wheel on the same GPU.

    python -m tests.integration.corpus.frozen_probe OUTPUT --wheel WHEEL --sha256 SHA \
        --references CAPTURE_DIRECTORY [CASE...]

Diagnostic only: no reference or regression-acceptance changes. Comparisons use actual RGB
pixels, never stored image hashes or tolerances. Each scene runs in a fresh process. Artifact
hashes identify the wheel and take bytes; those identities are distinct from the visual test.
"""

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path
from typing import cast

from PIL import Image
from tests.integration.corpus.case import (
    FPS,
    SIZE,
    Case,
    Json,
    discover,
    exact,
    seconds,
    source_hash,
)
from tests.integration.corpus.engines import TIMEOUT, environment
from tests.integration.corpus.frames import rgb
from tests.integration.corpus.frozen import (
    Comparison,
    Difference,
    NativeInterpreter,
    interpreter,
    prepare,
    same_adapter,
    verify,
)
from tests.integration.corpus.probe import _call, _metadata
from tests.integration.corpus.runtime import load, seed, the_scene

import manimgx
from manimgx import _engine
from manimgx.rendering.film import Frame


def compare(
    case: Case, reference: Path, native: Path, output: Path, *, negative: bool = False
) -> dict[str, Json]:
    baseline = interpreter(native)
    adapter = same_adapter(baseline, cast(NativeInterpreter, _engine))
    metadata = json.loads(
        (reference / case.name / "recording.json").read_text(encoding="utf-8")
    )
    take = reference / case.name / "recording.take"
    verify(take, metadata["sha256"])
    expected = baseline.Replay(take.read_bytes())
    if (expected.size, expected.fps, expected.frames) != (
        SIZE,
        FPS,
        metadata["frames"],
    ):
        raise ValueError("the reference's native timeline differs from its manifest")
    source = case.scene.read_bytes()
    if source_hash(source) != metadata["source"]:
        raise ValueError("the scene source differs from the reviewed capture")
    if negative:
        # A real source edit, compiled through the ordinary loader in this fresh process.
        # The control is run on basic_usage, whose original background is black.
        source = source.replace(
            b"def construct(self):\n",
            b"def construct(self):\n        self.camera.background_color = m.PINK\n",
            1,
        )
        if source_hash(source) == metadata["source"]:
            raise ValueError("the negative source control did not edit its fixture")
    seed()
    manimgx.config.pixel_width, manimgx.config.pixel_height = SIZE
    manimgx.config.frame_rate = FPS
    module = load(case.scene, source, f"corpus_scene_{case.name}")
    scene = the_scene(module, manimgx.Scene)()
    mismatches: list[Json] = []

    def changed(difference: Difference, old: bytes, new: bytes) -> None:
        mismatches.append(
            {
                "first": difference.first,
                "repeat": difference.repeat,
                "changed_pixels": difference.changed_pixels,
                "max_channel_difference": difference.max_channel_difference,
            }
        )
        if len(mismatches) <= 3:
            Image.frombytes("RGB", SIZE, old).save(
                output / f"reference-{difference.first:05}.png"
            )
            Image.frombytes("RGB", SIZE, new).save(
                output / f"actual-{difference.first:05}.png"
            )

    comparison = Comparison(expected, changed)

    def observe(frame: Frame) -> None:
        comparison.add(frame.index, frame.repeat, rgb(frame.pixels(), SIZE))

    started = time.monotonic()
    film = scene.render(frames=observe)
    comparison.finish(film.frame_count)
    same_duration = exact(seconds(scene.clock)) == exact(
        seconds(Fraction(metadata["duration"]))
    )
    same_frames = comparison.frames == expected.frames == film.frame_count
    return {
        "case": case.name,
        "status": "exact"
        if not mismatches and same_duration and same_frames
        else "different",
        "source": source_hash(source),
        "reference_source": str(metadata["source"]),
        "negative_source_control": negative,
        "adapter": cast(dict[str, Json], adapter),
        "reference_take_version": baseline.TAKE_VERSION,
        "actual_take_version": _engine.TAKE_VERSION,
        "frames": comparison.frames,
        "reference_frames": expected.frames,
        "duration": str(scene.clock),
        "reference_duration": str(metadata["duration"]),
        "same_duration": same_duration,
        "same_frame_count": same_frames,
        "changed_frames": comparison.changed_frames,
        "mismatches": mismatches,
        "seconds": time.monotonic() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--negative-source", action="store_true")
    parser.add_argument(
        "--capture-take",
        action="store_true",
        help="also record each scene in a fresh process",
    )
    parser.add_argument("--native", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    out, references = args.output.resolve(), args.references.resolve()
    out.mkdir(parents=True, exist_ok=True)
    known = {case.name: case for case in discover()}
    names = args.cases or list(known)
    if missing := set(names) - known.keys():
        parser.error(f"unknown cases: {sorted(missing)}")
    if args.worker:
        if args.native is None or len(names) != 1:
            parser.error("a worker needs one case and a prepared native artifact")
        result = compare(
            known[names[0]], references, args.native, out, negative=args.negative_source
        )
        (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        sys.exit((result["status"] == "exact") == args.negative_source)
    if args.wheel is None or args.sha256 is None:
        parser.error("a probe needs --wheel and its independently supplied --sha256")
    if args.jobs < 1 or args.jobs > 4:
        parser.error("use between one and four fresh worker processes")
    if args.negative_source and names != ["basic_usage"]:
        parser.error("the negative source control requires basic_usage alone")
    native = prepare(args.wheel, args.sha256, out / "reference-wheel")
    _metadata(out)
    (out / "reference-wheel.json").write_text(
        (native / "reference-wheel.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    results: dict[str, Json] = {}

    def run(name: str) -> tuple[str, Json]:
        directory = out / name
        directory.mkdir(exist_ok=True)
        (directory / "result.json").unlink(missing_ok=True)
        command = [
            sys.executable,
            "-m",
            "tests.integration.corpus.frozen_probe",
            str(directory),
            name,
            "--references",
            str(references),
            "--native",
            str(native),
            "--worker",
        ]
        if args.negative_source:
            command.append("--negative-source")
        with (directory / "probe.log").open("wb") as log:
            try:
                process = subprocess.run(
                    command,
                    cwd=known[name].dir,
                    env=environment(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=TIMEOUT["manimgx"],
                )
                result: dict[str, Json] = (
                    json.loads((directory / "result.json").read_text(encoding="utf-8"))
                    if (directory / "result.json").exists()
                    else {"status": "error"}
                )
                result["returncode"] = process.returncode
            except subprocess.TimeoutExpired as error:
                log.write(f"\n{error}\n".encode())
                result = {"status": "error", "returncode": 1, "error": str(error)}
        if args.capture_take:
            captured = _call(
                "tests.integration.corpus.probe",
                [str(directory), name, "--take"],
                known[name],
                directory / "recording.log",
            )
            result["captured_take"] = captured
            if not captured:
                result.update(status="error", returncode=1, error="take capture failed")
        return name, result

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for name, result in pool.map(run, names):
            results[name] = result
            (out / "results.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8"
            )
            status = result.get("status") if isinstance(result, dict) else "error"
            print(f"{len(results)}/{len(names)} {name}: {status}", flush=True)
    sys.exit(
        any(
            isinstance(result, dict) and result.get("returncode") != 0
            for result in results.values()
        )
    )


if __name__ == "__main__":
    main()
