# /// script
# requires-python = ">=3.13"
# ///
"""Create manimgx's executable for this machine, from its wheel in dist/: one file holding a
Python with manimgx and its locked dependencies installed.

The file is PyApp (https://ofek.dev/pyapp). Its first run unpacks the Python it holds; every
run then runs `manimgx` there, with no network and no Python on the machine. `manimgx self`
manages it: `self pip install PACKAGE` adds a package a scene imports, `self remove` deletes
what it unpacked, `self cache dist --remove` the copy of the Python it keeps.

Run it with `just create-executable`; it writes dist/manimgx-<os>-<arch>.tar.gz (a .zip on
Windows), after running what it made once.
"""

import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

PYAPP = "0.29.0"
PYTHON = "3.14"

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"
WINDOWS = sys.platform == "win32"
INTERPRETER = "python.exe" if WINDOWS else "bin/python3"  # in the Python's directory
SYSTEM = {"linux": "linux", "darwin": "macos", "win32": "windows"}[sys.platform]
MACHINE = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}[
    platform.machine().lower()
]


def run(*command: str | Path, env: dict[str, str] | None = None) -> None:
    print("$", *command, flush=True)
    subprocess.run([str(part) for part in command], check=True, env=env)


def the_wheel() -> Path:
    """The one manimgx wheel in dist/ (the workflows put this machine's there)."""
    wheels = sorted(DIST.glob("manimgx-*.whl"))
    if len(wheels) != 1:
        sys.exit(f"expected one manimgx wheel in {DIST}, found {len(wheels)}")
    return wheels[0]


def install_python(directory: Path) -> Path:
    """A standalone CPython (python-build-standalone, through uv), in its own directory."""
    run("uv", "python", "install", PYTHON, "--install-dir", directory, "--no-bin")
    # the installation itself, not the links uv adds beside it (cpython-3.14-… to cpython-3.14.N-…)
    (python,) = [
        path
        for path in directory.glob("cpython-*")
        if path.is_dir() and not path.is_symlink() and not path.is_junction()
    ]
    return python


def install_manimgx(python: Path, wheel: Path, work: Path) -> None:
    """manimgx, from its wheel, with its fonts (fonts/manimgx-fonts*, as this commit has
    them) and the dependencies uv.lock pins."""
    requirements = work / "requirements.txt"
    run(
        "uv", "export", "--frozen", "--package", "manimgx", "--no-default-groups",
        "--no-emit-workspace", "--no-hashes", "--output-file", requirements,
    )  # fmt: skip
    fonts = sorted((ROOT / "fonts").glob("manimgx-fonts*"))
    run(
        "uv", "pip", "install", "--python", python / INTERPRETER, "--break-system-packages",
        "--compile-bytecode", "--requirements", requirements, wheel, *fonts,
    )  # fmt: skip
    # the Python is manimgx's own: `manimgx self pip install` may add packages to it
    for marker in python.glob("**/EXTERNALLY-MANAGED"):
        marker.unlink()


def build_pyapp(distribution: Path, version: str, work: Path) -> Path:
    """PyApp, built with the distribution inside it: it unpacks it and runs `manimgx`."""
    # the distribution itself runs manimgx, installed in it already: no virtual environment,
    # no installation at runtime
    env = os.environ | {
        "PYAPP_PROJECT_NAME": "manimgx",
        "PYAPP_PROJECT_VERSION": version,
        "PYAPP_PYTHON_VERSION": PYTHON,
        "PYAPP_DISTRIBUTION_PATH": str(distribution),
        "PYAPP_DISTRIBUTION_PYTHON_PATH": INTERPRETER,
        "PYAPP_FULL_ISOLATION": "1",
        "PYAPP_SKIP_INSTALL": "1",
        "PYAPP_EXEC_SPEC": "manimgx.cli:main",
        "PYAPP_EXPOSE_PIP": "1",
        "PYAPP_EXPOSE_PYTHON": "1",
        "PYAPP_EXPOSE_CACHE": "1",
    }
    run(
        "cargo", "install", "pyapp", "--version", PYAPP, "--locked", "--force",
        "--root", work / "pyapp", env=env,
    )  # fmt: skip
    binary = work / "pyapp" / "bin" / ("pyapp.exe" if WINDOWS else "pyapp")
    executable = work / ("manimgx.exe" if WINDOWS else "manimgx")
    binary.rename(executable)
    return executable


def smoke_test(executable: Path) -> None:
    """Render a scene with it (scripts/release/smoke_test.py), then delete what it unpacked."""
    run(sys.executable, ROOT / "scripts" / "release" / "smoke_test.py", executable)
    run(executable, "self", "remove")
    run(executable, "self", "cache", "dist", "--remove")


def main() -> None:
    wheel = the_wheel()
    version = wheel.name.split("-")[1]
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        python = install_python(work / "python")
        install_manimgx(python, wheel, work)
        distribution = work / "python.tar.gz"
        with tarfile.open(distribution, "w:gz") as archive:
            for path in python.iterdir():
                archive.add(path, arcname=path.name)
        executable = build_pyapp(distribution, version, work)
        smoke_test(executable)
        # an archive keeps the file executable
        name = f"manimgx-{SYSTEM}-{MACHINE}"
        if WINDOWS:
            created = DIST / f"{name}.zip"
            with zipfile.ZipFile(created, "w", zipfile.ZIP_DEFLATED) as out:
                out.write(executable, executable.name)
        else:
            created = DIST / f"{name}.tar.gz"
            with tarfile.open(created, "w:gz") as out:
                out.add(executable, arcname=executable.name)
    print(f"created {created}")


if __name__ == "__main__":
    main()
