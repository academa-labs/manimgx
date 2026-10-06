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

import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

PYAPP = "0.29.0"
PYAPP_SHA256 = "0ad1267db069a83e16dad2a42b0d01c727f5a9da7614330f44b66876da2d15f6"
PYTHON = "3.14"

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"
WINDOWS = sys.platform == "win32"
INTERPRETER = "python.exe" if WINDOWS else "bin/python3"  # in the Python's directory
SYSTEM = {"linux": "linux", "darwin": "macos", "win32": "windows"}[sys.platform]
MACHINE = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}[
    platform.machine().lower()
]


def run(
    *command: str | Path,
    env: dict[str, str] | None = None,
    cwd: Path = ROOT,
) -> None:
    print("$", *command, flush=True)
    subprocess.run([str(part) for part in command], check=True, env=env, cwd=cwd)


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


def launcher_sources(work: Path) -> Path:
    """The exact launcher input, including its own complete locked Cargo graph."""
    url = f"https://static.crates.io/crates/pyapp/pyapp-{PYAPP}.crate"
    run(
        "cargo", "run", "--locked", "--manifest-path", ROOT / "rust/Cargo.toml",
        "-p", "fetch", "--bin", "fetch-file", "--", url, PYAPP_SHA256,
        env=os.environ | {"OUT_DIR": str(work)},
    )  # fmt: skip
    with tarfile.open(work / PYAPP_SHA256) as archive:
        archive.extractall(work, filter="data")
    source = work / f"pyapp-{PYAPP}"
    config = source / ".cargo" / "config.toml"
    config.parent.mkdir(exist_ok=True)
    # Keep upstream target flags, including Windows' static C runtime.
    with config.open("a", encoding="utf-8") as output:
        output.write("\n")
        output.flush()
        subprocess.run(
            ["cargo", "vendor", "--locked", "vendor"],
            cwd=source,
            stdout=output,
            check=True,
        )
    return source


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def build_pyapp(distribution: Path, version: str, work: Path, source: Path) -> Path:
    """PyApp, built with the distribution inside it: it unpacks it and runs `manimgx`."""
    # the distribution itself runs manimgx, installed in it already: no virtual environment,
    # no installation at runtime
    env = os.environ | {
        # Keep compiled output outside the source closure retained for the release.
        "CARGO_TARGET_DIR": str(work / "target"),
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
        "cargo", "install", "--path", source, "--locked", "--offline", "--force",
        "--root", work / "pyapp", env=env, cwd=source,
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
        source = launcher_sources(work)
        retained = ROOT / "release-sources" / f"executable-{SYSTEM}-{MACHINE}"
        retained.mkdir(parents=True, exist_ok=True)
        # PyApp's build script copies the binary distribution into its source tree.
        # Retain the input before that generated payload is written.
        with tarfile.open(retained / "pyapp.tar.xz", "w:xz") as out:
            out.add(source, arcname="pyapp")
        executable = build_pyapp(distribution, version, work, source)
        target = next(
            line.removeprefix("host: ")
            for line in subprocess.check_output(
                ["rustc", "-vV"], text=True, encoding="utf-8"
            ).splitlines()
            if line.startswith("host: ")
        )
        notice = work / "LICENSE-PYAPP"
        run(
            sys.executable,
            ROOT / "scripts/release/licenses.py",
            "--crate",
            source,
            target,
            notice,
        )
        receipt = work / "build-inputs.json"
        receipt.write_text(
            json.dumps(
                {
                    "wheel": {"name": wheel.name, "sha256": sha256(wheel)},
                    "launcher": {
                        "version": PYAPP,
                        "url": f"https://static.crates.io/crates/pyapp/pyapp-{PYAPP}.crate",
                        "sha256": PYAPP_SHA256,
                        "lock_sha256": sha256(source / "Cargo.lock"),
                        "target": target,
                    },
                    "distribution_sha256": sha256(distribution),
                    "executable_sha256": sha256(executable),
                    "source_sha256": sha256(retained / "pyapp.tar.xz"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (retained / "manifest.json").write_bytes(receipt.read_bytes())
        smoke_test(executable)
        # an archive keeps the file executable
        name = f"manimgx-{SYSTEM}-{MACHINE}"
        if WINDOWS:
            created = DIST / f"{name}.zip"
            with zipfile.ZipFile(created, "w", zipfile.ZIP_DEFLATED) as out:
                for path in (executable, notice, receipt):
                    out.write(path, path.name)
        else:
            created = DIST / f"{name}.tar.gz"
            with tarfile.open(created, "w:gz") as out:
                for path in (executable, notice, receipt):
                    out.add(path, arcname=path.name)
    print(f"created {created}")


def verify_sources(directory: Path) -> None:
    """Every executable contributed the unchanged sources of its actual launcher."""
    for target in ("linux-x86_64", "linux-arm64", "macos-arm64", "windows-x86_64"):
        source = directory / f"executable-{target}"
        receipt = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        if sha256(source / "pyapp.tar.xz") != receipt["source_sha256"]:
            raise ValueError(f"{target}: the executable's retained source changed")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--verify-sources"]:
        verify_sources(Path(sys.argv[2]))
    else:
        main()
