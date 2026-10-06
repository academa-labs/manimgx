"""Compare the frozen authoring package and today's wheel on the same host.

    python -m tests.integration.corpus.frozen_probe OUTPUT [CASE...] \
        --wheel WHEEL --sha256 SHA --lock FROZEN_UV_LOCK

Diagnostic only: canonical movies, case facts and human reviews are never changed. Both
packages use the ordinary corpus runner in fresh processes. The candidate compares every RGB
pixel against a transient lossless reference and still passes the product's MP4 count check.
"""

import argparse
import concurrent.futures
import dataclasses
import json
import sys
import time
from pathlib import Path

from tests.integration.corpus import engines
from tests.integration.corpus.case import (
    ROOT,
    Case,
    Failure,
    Json,
    discover,
    frames_to_json,
)
from tests.integration.corpus.frozen import dependencies, prepare
from tests.integration.corpus.probe import _metadata


def compare(
    case: Case, package: Path, output: Path, *, negative: bool = False
) -> dict[str, Json]:
    """Run one baseline and one candidate through the same isolated execution boundary."""
    output.mkdir(parents=True, exist_ok=True)
    facts = case.facts()
    if not case.current(facts):
        return {
            "status": "error",
            "error": "the scene source differs from its canonical facts",
        }
    started = time.monotonic()
    baseline = engines.run(
        case,
        "manimgx",
        package=package,
        video=output / "reference.mkv",
        log=output / "reference.log",
        compact_video=False,
    )
    if isinstance(baseline.frames, Failure):
        return {"status": "error", "error": baseline.frames.error}
    if facts is None or baseline.source != facts.source:
        return {
            "status": "error",
            "error": "the source changed while the reference rendered",
        }
    reference = output / "reference.json"
    reference.write_text(json.dumps(frames_to_json(baseline.frames)), encoding="utf-8")
    source = None
    if negative:
        original = case.scene.read_bytes()
        changed = original.replace(
            b"def construct(self):\n",
            b"def construct(self):\n        self.camera.background_color = m.PINK\n",
            1,
        )
        if changed == original:
            raise ValueError("the negative source control did not edit its fixture")
        source = output / "source.py"
        source.write_bytes(changed)
    actual = engines.run(
        case,
        "manimgx",
        mp4=True,
        reference=reference,
        source=source,
        differences=output,
        log=output / "actual.log",
    )
    if isinstance(actual.frames, Failure):
        return {"status": "error", "error": actual.frames.error}
    if not negative and actual.source != baseline.source:
        return {
            "status": "error",
            "error": "the source changed between the two renders",
        }
    if baseline.adapter != actual.adapter:
        return {
            "status": "error",
            "error": "the baseline and candidate used different adapters",
        }
    same_duration = baseline.frames.duration == actual.frames.duration
    same_timeline = baseline.frames.timeline == actual.frames.timeline
    same_frames = (
        baseline.frames.count
        == actual.frames.count
        == actual.film_frames
        == actual.mp4_frames
    )
    return {
        "case": case.name,
        "status": "exact"
        if not actual.differences and same_duration and same_timeline and same_frames
        else "different",
        "source": actual.source,
        "reference_source": baseline.source,
        "negative_source_control": negative,
        "adapter": dict[str, Json](actual.adapter or {}),
        "frames": actual.frames.count,
        "reference_frames": baseline.frames.count,
        "duration": str(actual.frames.duration),
        "reference_duration": str(baseline.frames.duration),
        "same_duration": same_duration,
        "same_frame_count": same_frames,
        "same_timeline": same_timeline,
        "changed_frames": sum(d.repeat for d in actual.differences),
        "mismatches": [dataclasses.asdict(d) for d in actual.differences],
        "seconds": time.monotonic() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--negative-source", action="store_true")
    parser.add_argument("--expect-different", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        parser.error("use between one and four independent case comparisons")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    known = {case.name: case for case in discover()}
    names = args.cases or list(known)
    if missing := set(names) - known.keys():
        parser.error(f"unknown cases: {sorted(missing)}")
    if args.negative_source and names != ["basic_usage"]:
        parser.error("the negative source control requires basic_usage alone")
    lock = dependencies(args.lock, ROOT / "uv.lock")
    package = prepare(args.wheel, args.sha256, out / "reference-wheel")
    _metadata(out)
    (out / "reference.json").write_text(
        json.dumps({"wheel": args.sha256, "dependency_lock": lock}), encoding="utf-8"
    )
    results: dict[str, Json] = {}

    def run(name: str) -> tuple[str, dict[str, Json]]:
        result = compare(
            known[name], package, out / name, negative=args.negative_source
        )
        (out / name / "result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        return name, result

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for name, result in pool.map(run, names):
            results[name] = result
            (out / "results.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8"
            )
            print(f"{len(results)}/{len(names)} {name}: {result['status']}", flush=True)
    wanted = "different" if args.negative_source or args.expect_different else "exact"
    sys.exit(
        any(
            isinstance(result, dict) and result.get("status") != wanted
            for result in results.values()
        )
    )


if __name__ == "__main__":
    main()
