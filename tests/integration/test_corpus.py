"""The corpus's three checks, per case.

1. `test_same_source`: both references were rendered from this exact `scene.py`, which is the
   case's only code and reaches the engine only through `manimgx`'s top level (and its types,
   `manimgx.typing`) — so CE and manimgx ran the same program.
2. `test_types`: the scene is type safe as written for manimgx — `ty` with every rule, no
   escape from the checker, and no value manimgx leaves `Any` or `Unknown`.
3. `test_regression`: the scene renders and the product exports it; today's manimgx holds
   exactly to its stored frames, duration and timeline, regardless of CE's result or the
   case's review status.

This module only checks. `python -m tests.integration.corpus` renders and reviews.
"""

import ast
import re
import tempfile
from pathlib import Path

import pytest
from PIL import Image
from tests.integration.corpus import compare, engines, typecheck
from tests.integration.corpus.case import (
    FPS,
    METRICS,
    SIZE,
    Case,
    Failure,
    Frames,
    discover,
    settings,
)
from tests.integration.corpus.frames import decode

CASES = discover()
IDS = [case.name for case in CASES]
SETTINGS = settings()
DIFFS = Path(__file__).resolve().parent / "_diffs"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_same_source(case: Case) -> None:
    others = sorted(p.name for p in case.dir.glob("*.py") if p.name != "scene.py")
    assert not others, f"a case has one source, scene.py; it also holds {others}"
    imported = _imported(ast.parse(case.scene.read_bytes()))
    direct = sorted({line for line, name in imported if name.split(".")[0] == "manim"})
    assert not direct, f"imports Manim CE directly (lines {direct}): use manimgx"
    inner = sorted(
        {
            line
            for line, name in imported
            if name.startswith("manimgx.") and name != "manimgx.typing"
        }
    )
    assert not inner, f"imports manimgx's modules (lines {inner}): use its top level"
    facts = case.facts()
    assert facts is not None, f"no references yet: just corpus render {case.name}"
    assert facts.source == case.source_hash(), (
        "scene.py changed since its references were rendered: "
        f"just corpus render {case.name}"
    )
    assert (facts.size, facts.fps) == (SIZE, FPS), "rendered at another size or rate"
    for engine in ("manimgx", "ce"):
        if isinstance(facts.render(engine), Frames):
            video = case.video(engine)
            sidecar = case.video_hash(engine)
            assert sidecar.exists(), f"{sidecar.name} is missing"
            digest, separator, filename = (
                sidecar.read_text(encoding="ascii").strip().partition("  ")
            )
            assert separator == "  ", f"{sidecar.name} is malformed"
            assert filename == video.name, f"{sidecar.name} is malformed"
            assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None, (
                f"{sidecar.name} is malformed"
            )


def _imported(tree: ast.Module) -> list[tuple[int, str]]:
    """Each module a scene imports, with the line that imports it."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.append((node.lineno, node.module))
    return found


@pytest.fixture(scope="session")
def type_report() -> typecheck.TypeReport:
    return typecheck.report(CASES)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_types(case: Case, type_report: typecheck.TypeReport) -> None:
    problems = type_report.problems(case)
    if problems:
        pytest.fail("\n".join(problems), pytrace=False)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_regression(case: Case) -> None:
    result = engines.run(case, "manimgx", mp4=True)
    if isinstance(result.frames, Failure):
        pytest.fail(f"the scene does not render: {result.frames.error}", pytrace=False)
    assert result.mp4_frames == result.film_frames, (
        f"the product's MP4 shows {result.mp4_frames} frames of the film's "
        f"{result.film_frames}"
    )
    facts = case.facts()
    assert facts is not None
    expected = facts.manimgx
    assert isinstance(expected, Frames)
    if result.frames != expected:
        pytest.fail(_explain(case, expected, result.frames), pytrace=False)


def _explain(case: Case, expected: Frames, fresh: Frames) -> str:
    """What changed in the film (the worst frame pair is written under `_diffs/`)."""
    was, now = expected.hashes(), fresh.hashes()
    changed = [i for i, (a, b) in enumerate(zip(was, now, strict=False)) if a != b]
    lines = [f"{case.name}: today's manimgx differs from its reference"]
    if fresh.duration != expected.duration:
        lines.append(f"  duration {fresh.duration}s instead of {expected.duration}s")
    if fresh.timeline != expected.timeline:
        lines.append(f"  timeline {fresh.timeline!r} instead of {expected.timeline!r}")
    if len(was) != len(now):
        lines.append(f"  {len(now)} frames instead of {len(was)}")
    if changed:
        lines.append(
            f"  {len(changed)} frames differ, first {changed[0]}, last {changed[-1]}"
        )
    if changed and case.video("manimgx").exists():
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "fresh.mkv"
            engines.run(case, "manimgx", video=video)
            wanted = set(changed[:200])
            old = {
                i: f
                for i, f in enumerate(decode(case.video("manimgx"), SIZE))
                if i in wanted
            }
            new = {i: f for i, f in enumerate(decode(video, SIZE)) if i in wanted}
        column = METRICS.index(SETTINGS.metric)
        errors = {i: compare.measure(old[i], new[i])[column] for i in sorted(wanted)}
        worst = max(errors, key=lambda i: errors[i])
        lines.append(
            f"  largest change {errors[worst]:.1f} ({SETTINGS.metric}) at frame {worst}"
        )
        out = DIFFS / case.name
        out.mkdir(parents=True, exist_ok=True)
        sheet = Image.new("RGB", (SIZE[0] * 2, SIZE[1]))
        sheet.paste(Image.fromarray(old[worst]), (0, 0))
        sheet.paste(Image.fromarray(new[worst]), (SIZE[0], 0))
        sheet.save(out / f"reference_vs_today_{worst:04d}.png")
        lines.append(
            f"  reference | today: {out / f'reference_vs_today_{worst:04d}.png'}"
        )
    elif changed:
        lines.append(
            "  reference video unavailable; regenerate it for a frame comparison"
        )
    lines.append(
        f"  intended? just corpus render {case.name} (its review then needs renewing)"
    )
    return "\n".join(lines)
