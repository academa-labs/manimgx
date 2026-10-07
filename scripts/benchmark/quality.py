"""Render the linked-rings frame at 2.5 seconds on dark and light backgrounds."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image
from scripts.benchmark.run import executable

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "scenes"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gx-python", default=sys.executable)
    parser.add_argument("--ce-python", default=sys.executable)
    parser.add_argument("--gl-python", required=True)
    parser.add_argument("--blender", default="blender")
    args = parser.parse_args()
    for option in ("gx_python", "ce_python", "gl_python", "blender"):
        setattr(args, option, executable(getattr(args, option)))
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    native = args.out / "native"
    native.mkdir()
    images = args.out / "images"
    images.mkdir()
    env = os.environ | {"PYTHONPATH": str(SOURCES), "PYTHONDONTWRITEBYTECODE": "1"}
    for engine in (
        "manimgx",
        "manim_ce",
        "manimgl",
        "blender_workbench",
        "blender_eevee",
    ):
        target = native / f"{engine}.png"
        if engine.startswith("blender_"):
            command = [
                args.blender,
                "-b",
                "--factory-startup",
                "--python-exit-code",
                "1",
                "-P",
                str(SOURCES / "linked_rings_blender.py"),
                "--",
                "--engine",
                engine.removeprefix("blender_"),
                "--out",
                str(target),
            ]
        else:
            python = {
                "manimgx": args.gx_python,
                "manim_ce": args.ce_python,
                "manimgl": args.gl_python,
            }[engine]
            command = [
                python,
                str(SOURCES / "quality_manim.py"),
                "--engine",
                engine,
                "--out",
                str(target),
            ]
        print(engine, flush=True)
        (native / f"{engine}-command.json").write_text(
            json.dumps(command, indent=2) + "\n", encoding="utf-8"
        )
        with (native / f"{engine}.log").open("wb") as log:
            subprocess.run(
                command,
                cwd=native,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=120,
            )
        with Image.open(target) as source:
            foreground = source.convert("RGBA")
            if (
                foreground.size != (1920, 1080)
                or foreground.getchannel("A").getextrema()[0] != 0
            ):
                raise ValueError(f"Expected a transparent 1080p frame: {target}")
            for suffix, color in (("", "#0B0C0F"), ("-light", "#FFFFFF")):
                background = Image.new("RGBA", foreground.size, color)
                background.alpha_composite(foreground)
                background.convert("RGB").save(images / f"{engine}{suffix}.png")
    print(images)


if __name__ == "__main__":
    main()
