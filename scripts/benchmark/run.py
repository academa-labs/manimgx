"""Time manimgx, Manim Community Edition, ManimGL and Blender on the same scenes.

    uv run --frozen python scripts/benchmark/run.py [--runs 5] [--only orbit,morph] [--tools manimgx,blender_workbench]

Each scene is the same film in each tool's own idiom: 1920 x 1080 at 60 fps, written to an
H.264 MP4 with the tool's own encoder settings. manimgx's are the timed benchmarks' workloads
(`tests/benchmarks/scenes/<scene>.py`); the others are here (`scenes/<scene>_<tool>.py`). A
run is the tool's command, in a fresh process and a fresh folder (its caches with it: Manim
CE's and ManimGL's LaTeX, manimgx's Typst layouts), timed from launch to exit, when the MP4
is written. Each contender renders a scene once to warm up (unless that takes over two
minutes: it counts then), then again, the contenders taking turns, until it has five runs
(three if a run takes over a minute, one if over ten). The medians go to `results.json`,
with every run, the versions and the machine; each MP4 is checked for its length, then
deleted.

The tools:
- manimgx and Manim CE (0.21.0): this repository's environment, with the `ce` group
  (`uv sync --group ce`).
- ManimGL (1.7.2): its own environment, e.g. `uv venv --python 3.12 ENV` and
  `uv pip install --python ENV manimgl==1.7.2 setuptools` (`--manimgl ENV`); its LaTeX
  template is its minimal one, "basic".
- Blender (5.2 LTS), headless, twice: with EEVEE, its default renderer, and with Workbench,
  its fastest (`--blender PATH`). It has no math typesetting, so it renders the 3D scenes.
"""

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
SCENES = HERE / "scenes"
WORKLOADS = ROOT / "tests" / "benchmarks" / "scenes"  # manimgx's scenes
BIN = ROOT / ".venv" / "bin"
SCENE_CLASSES = {"orbit": "Orbit", "morph": "Morph", "explainer": "Explainer"}
SECONDS = {"orbit": 10.0, "morph": 10.0, "explainer": 9.5}
WARM_LIMIT, SLOW, SLOWER = 120.0, 60.0, 600.0


@dataclass(frozen=True)
class Contender:
    """A tool, as the chart names it, and how it renders a scene into a folder."""

    name: str
    label: str
    scenes: tuple[str, ...]

    def command(self, scene: str, folder: Path, args: argparse.Namespace) -> list[str]:
        """The command that renders `scene` into `folder`."""
        mine = self.tool == "manimgx"
        file = str(
            WORKLOADS / f"{scene}.py" if mine else SCENES / f"{scene}_{self.tool}.py"
        )
        cls = SCENE_CLASSES[scene]
        if mine:
            return [str(BIN / "manimgx"), "render", file, "-o", str(folder / "out.mp4")]
        if self.tool == "manim_ce":
            return [
                str(BIN / "manim"),
                "render",
                "-qh",
                "--disable_caching",
                "--media_dir",
                str(folder),
                file,
                cls,
            ]
        if self.tool == "manimgl":
            config = folder / "config.yml"
            config.write_text(
                f'directories:\n  cache: "{folder / "cache"}"\n'
                'camera:\n  fps: 60\ntex:\n  template: "basic"\n',
                encoding="utf-8",
            )
            return [
                str(Path(args.manimgl) / "bin" / "manimgl"),
                file,
                cls,
                "-w",
                "--hd",  # 60 fps comes from the config (its --fps flag passes a string)
                "--video_dir",
                str(folder),
                "--config_file",
                str(config),
            ]
        engine = self.name.removeprefix("blender_").upper()
        return [
            args.blender,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "-P",
            file,
            "--",
            "--engine",
            engine,
            "--out",
            str(folder / "out.mp4"),
        ]

    @property
    def tool(self) -> str:
        """The tool whose scene files it runs."""
        return "blender" if self.name.startswith("blender") else self.name


CONTENDERS = [
    Contender("manimgx", "manimgx", ("orbit", "morph", "explainer")),
    Contender("manimgl", "ManimGL", ("orbit", "morph", "explainer")),
    Contender("blender_workbench", "Blender (Workbench)", ("orbit", "morph")),
    Contender("blender_eevee", "Blender (EEVEE)", ("orbit", "morph")),
    Contender("manim_ce", "Manim CE", ("orbit", "morph", "explainer")),
]


def run(contender: Contender, scene: str, args: argparse.Namespace) -> dict[str, float]:
    """Render once, in a fresh folder, and measure it; the MP4 is checked, then deleted."""
    folder = Path(tempfile.mkdtemp(prefix=f"bench-{scene}-{contender.name}-"))
    # a TMPDIR of its own: manimgx caches Typst's layouts there
    env = os.environ | {"TMPDIR": str(folder)}
    load = os.getloadavg()[0]
    log = folder / "stderr.txt"
    with log.open("wb") as stderr:
        start = time.perf_counter()
        pid = subprocess.Popen(
            contender.command(scene, folder, args),
            cwd=folder,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        ).pid
        _, status, usage = os.wait4(pid, 0)  # its CPU time, its children's included
        wall = time.perf_counter() - start
    if status:
        errors = log.read_text(encoding="utf-8", errors="replace")[-3000:]
        sys.exit(f"{contender.name} failed on {scene}:\n{errors}")
    unit = 1024 if platform.system() == "Darwin" else 1  # ru_maxrss: bytes, or KiB
    videos = [p for p in folder.rglob("*.mp4") if "partial_movie_files" not in p.parts]
    if len(videos) != 1:
        sys.exit(f"{contender.name} wrote {len(videos)} videos for {scene}")
    probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size",
                "-of",
                "json",
                str(videos[0]),
            ],
            capture_output=True,
            check=True,
        ).stdout
    )["format"]
    duration = float(probe["duration"])
    if abs(duration - SECONDS[scene]) > 0.1:
        sys.exit(f"{contender.name}'s {scene} lasts {duration:.2f} s")
    if args.keep:
        kept = Path(args.keep) / f"{scene}_{contender.name}.mp4"
        kept.parent.mkdir(parents=True, exist_ok=True)
        if not kept.exists():
            shutil.copyfile(videos[0], kept)
    shutil.rmtree(folder)
    return {
        "wall": round(wall, 3),
        "cpu": round(usage.ru_utime + usage.ru_stime, 2),
        "memory_mb": round(usage.ru_maxrss / unit / 1024),
        "video_mb": round(int(probe["size"]) / 1e6, 1),
        "load": round(load, 2),
    }


def versions(tools: list[str], args: argparse.Namespace) -> dict[str, str]:
    """The version of each tool that ran."""

    def output(*command: str) -> str:
        return subprocess.run(command, capture_output=True, text=True).stdout.strip()

    found = {}
    if "manimgx" in tools:
        found["manimgx"] = output(str(BIN / "manimgx"), "--version").split()[-1]
    if "manim_ce" in tools:
        found["manim_ce"] = output(
            str(BIN / "python"), "-c", "import manim; print(manim.__version__)"
        )
    if "manimgl" in tools:
        python = str(Path(args.manimgl) / "bin" / "python")
        found["manimgl"] = output(
            python, "-c", "import importlib.metadata as m; print(m.version('manimgl'))"
        )
    if any(tool.startswith("blender") for tool in tools):
        found["blender"] = (
            output(args.blender, "--version").splitlines()[0].removeprefix("Blender ")
        )
    return found


def sysctl(key: str) -> str:
    """A value of macOS's kernel settings."""
    command = ["sysctl", "-n", key]
    return subprocess.run(command, capture_output=True, text=True).stdout.strip()


def machine() -> dict[str, str]:
    """The machine the runs were on."""
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "cpus": str(os.cpu_count()),
    }
    if platform.system() == "Darwin":
        info |= {
            "cpu": sysctl("machdep.cpu.brand_string"),
            "memory": f"{int(sysctl('hw.memsize')) // 2**30} GB",
            "os": f"macOS {platform.mac_ver()[0]}",
        }
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--only", default=",".join(SCENE_CLASSES))
    parser.add_argument("--tools", default=",".join(c.name for c in CONTENDERS))
    parser.add_argument("--manimgl", help="ManimGL's environment")
    parser.add_argument(
        "--blender",
        default=shutil.which("blender")
        or "/Applications/Blender.app/Contents/MacOS/Blender",
    )
    parser.add_argument("--keep", help="a folder to keep each contender's first MP4 in")
    parser.add_argument("--out", default=str(HERE / "results.json"))
    args = parser.parse_args()
    scenes, tools = args.only.split(","), args.tools.split(",")
    if "manimgl" in tools and not args.manimgl:
        parser.error(
            "ManimGL needs its environment: --manimgl ENV (or leave it out of --tools)"
        )
    pairs = [
        (c, s) for s in scenes for c in CONTENDERS if c.name in tools and s in c.scenes
    ]
    runs: dict[tuple[str, str], list[dict[str, float]]] = {
        (c.name, s): [] for c, s in pairs
    }
    wanted: dict[tuple[str, str], int] = {}
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    for contender, scene in pairs:  # the warm-up
        first = run(contender, scene, args)
        slow = first["wall"] > WARM_LIMIT
        wanted[contender.name, scene] = (
            args.runs if first["wall"] < SLOW else 3 if first["wall"] < SLOWER else 1
        )
        if slow:
            runs[contender.name, scene].append(first)
        print(
            f"warm-up {scene:9} {contender.label:20} {first['wall']:8.2f} s", flush=True
        )
    while any(len(runs[k]) < wanted[k] for k in runs):
        for contender, scene in pairs:
            if len(runs[contender.name, scene]) < wanted[contender.name, scene]:
                result = run(contender, scene, args)
                runs[contender.name, scene].append(result)
                print(
                    f"{scene:9} {contender.label:20} {result['wall']:8.2f} s  load"
                    f" {result['load']}",
                    flush=True,
                )
    medians = {
        key: statistics.median(r["wall"] for r in rows) for key, rows in runs.items()
    }
    results = {
        "date": time.strftime("%Y-%m-%d"),
        "commit": commit,
        "machine": machine(),
        "versions": versions(tools, args),
        "scenes": {
            scene: {
                c.name: {
                    "label": c.label,
                    "median": round(medians[c.name, scene], 2),
                    "runs": runs[c.name, scene],
                }
                for c, s in pairs
                if s == scene
            }
            for scene in scenes
        },
    }
    Path(args.out).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for contender, scene in pairs:
        median, base = medians[contender.name, scene], medians.get(("manimgx", scene))
        times = f"×{median / base:.1f}" if base else ""
        print(f"{scene:9} {contender.label:20} {median:8.2f} s  {times}")


if __name__ == "__main__":
    main()
