"""A pending PyPI publisher identifies one project by its workflow and environment.
The release must route only that project's distributions to it, and publish the fonts
before anything that installs manimgx from PyPI.
"""

import json
import subprocess
import tarfile
import tomllib
import zipfile
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TextIO

import pytest
import yaml
from scripts.release import create_executable, linux_sources, smoke_test

ROOT = Path(__file__).parents[1]
JOBS = yaml.safe_load(
    (ROOT / ".github/workflows/release.yaml").read_text(encoding="utf-8")
)["jobs"]


def test_pending_publishers_have_distinct_environments() -> None:
    publishers = {"manimgx": JOBS["pypi"]["environment"]["name"]}
    fonts = JOBS["pypi-fonts"]
    assert fonts["environment"]["name"] == "${{ matrix.environment }}"
    for entry in fonts["strategy"]["matrix"]["include"]:
        assert entry["package"] not in publishers
        publishers[entry["package"]] = entry["environment"]

    # These are the identities registered on PyPI, including the first-release publishers.
    assert publishers == {
        "manimgx": "pypi",
        "manimgx-fonts": "pypi-fonts",
        "manimgx-fonts-cjk": "pypi-fonts-cjk",
    }
    assert len(set(publishers.values())) == len(publishers)


def test_wheel_jobs_expand_platform_in_the_same_shell_on_every_os() -> None:
    wheel = yaml.safe_load(
        (ROOT / ".github/workflows/create-wheels.yaml").read_text(encoding="utf-8")
    )["jobs"]["wheel"]
    assert wheel["defaults"]["run"]["shell"] == "bash"
    build = next(step for step in wheel["steps"] if "PLATFORM" in step.get("env", {}))
    assert "${PLATFORM}" in build["run"]


def test_windows_diagnostic_pairs_the_wheel_with_its_original_source() -> None:
    job = yaml.safe_load(
        (ROOT / ".github/workflows/windows-diagnostic.yaml").read_text(encoding="utf-8")
    )["jobs"]["diagnose"]
    steps = job["steps"]
    source = next(step for step in steps if step.get("id") == "source")
    checkout = next(
        step for step in steps if step.get("uses", "").startswith("actions/checkout@")
    )
    download = next(
        step
        for step in steps
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert source["env"]["WHEEL_RUN"] == download["with"]["run-id"]
    assert checkout["with"]["ref"] == "${{ steps.source.outputs.revision }}"
    assert ".head_sha" in source["run"]
    run = next(step for step in steps if "TEST_ARGS" in step.get("env", {}))
    assert 'shlex.split(os.environ["TEST_ARGS"])' in run["run"]
    assert "${{ inputs.testargs }}" not in run["run"]


@pytest.mark.parametrize("package", ["manimgx-fonts", "manimgx-fonts-cjk"])
def test_font_artifacts_contain_only_their_own_package(
    package: str, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    expected = set()
    for manifest in sorted((ROOT / "fonts").glob("*/pyproject.toml")):
        project = tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]
        name = project["name"].replace("-", "_")
        version = project["version"]
        for suffix in [".tar.gz", "-py3-none-any.whl"]:
            filename = f"{name}-{version}{suffix}"
            (dist / filename).touch()
            if project["name"] == package:
                expected.add(filename)

    upload = next(
        step["with"]
        for step in JOBS["sdist"]["steps"]
        if step.get("with", {}).get("name") == package
    )
    assert expected
    assert {path.name for path in tmp_path.glob(upload["path"])} == expected

    download = next(
        step["with"]
        for step in JOBS["pypi-fonts"]["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert download["name"] == "${{ matrix.package }}"


def test_engine_publisher_excludes_fonts_and_github_only_artifacts() -> None:
    download = next(
        step["with"]
        for step in JOBS["pypi"]["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    # The download action's brace alternatives select artifact names, not filenames.
    patterns = download["pattern"].strip("{}").split(",")
    wheels = {
        f"wheel-{entry['platform']}"
        for entry in yaml.safe_load(
            (ROOT / ".github/workflows/create-wheels.yaml").read_text(encoding="utf-8")
        )["jobs"]["wheel"]["strategy"]["matrix"]["include"]
    }
    artifacts = wheels | {
        "sdist",
        "source",
        "manimgx-fonts",
        "manimgx-fonts-cjk",
        "executable-linux-x86_64",
    }
    selected = {
        artifact
        for artifact in artifacts
        if any(fnmatchcase(artifact, pattern) for pattern in patterns)
    }
    assert selected == wheels | {"sdist"}


def test_consumers_wait_for_the_font_packages() -> None:
    assert "pypi-fonts" in JOBS["pypi"]["needs"]
    for job in ["npm", "docker", "publish"]:
        assert "pypi" in JOBS[job]["needs"]


def test_release_smoke_records_decoded_audio_and_a_complete_versioned_take() -> None:
    scene: dict[str, object] = {}
    exec(smoke_test.scene_source(), scene)
    chunks: list[bytes] = []
    film = scene["Smoke"]().render(take=chunks.append)  # ty: ignore[call-non-callable]
    take = b"".join(chunks)
    smoke_test.validate_take(take, film.frame_count)
    # A nonempty/truncated/failed take used to pass the artifact smoke gate.
    for bad in [take[:-6], take[:-1], take[:-1] + b"\x01"]:
        with pytest.raises((AssertionError, ValueError)):
            smoke_test.validate_take(bad, film.frame_count)


@pytest.mark.parametrize("known", [0, 1, 2])
def test_linux_source_inventory_covers_every_library_that_was_bundled(
    tmp_path: Path, known: int
) -> None:
    wheel = tmp_path / "wheel.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in ["libone.so", "libtwo.so"]:
            archive.writestr(f"manimgx.libs/{name}", b"library")
        archive.writestr(
            "manimgx.dist-info/sboms/auditwheel.cdx.json",
            json.dumps(
                {
                    "components": [{"name": "manimgx"}]
                    + [
                        {
                            "name": name,
                            "version": "1.0-2.el8",
                            "purl": f"pkg:rpm/almalinux/{name}@1.0-2.el8",
                        }
                        for name in ["one", "two"][:known]
                    ]
                }
            ),
        )
    if known < 2:
        with pytest.raises(ValueError, match="every bundled library"):
            linux_sources.bundled_packages(wheel)
    else:
        assert linux_sources.bundled_packages(wheel) == {
            "one-1.0-2.el8",
            "two-1.0-2.el8",
        }


def test_source_archive_waits_for_the_platform_builds_that_choose_its_sources() -> None:
    assert set(JOBS["sdist"]["needs"]) == {"wheels", "executables"}
    download = next(
        step["with"]
        for step in JOBS["sdist"]["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert download["pattern"] == "sources-*"


def test_executable_sources_reject_missing_and_changed_platform_archives(
    tmp_path: Path,
) -> None:
    for platform in ("linux-x86_64", "linux-arm64", "macos-arm64", "windows-x86_64"):
        source = tmp_path / f"executable-{platform}"
        source.mkdir()
        archive = source / "pyapp.tar.xz"
        archive.write_bytes(b"the actual launcher sources and locked dependencies")
        (source / "manifest.json").write_text(
            json.dumps({"source_sha256": create_executable.sha256(archive)}),
            encoding="utf-8",
        )
        if platform != "windows-x86_64":
            with pytest.raises(FileNotFoundError):
                create_executable.verify_sources(tmp_path)
    create_executable.verify_sources(tmp_path)
    archive.write_bytes(b"other sources")
    with pytest.raises(ValueError, match="retained source changed"):
        create_executable.verify_sources(tmp_path)


def test_launcher_build_keeps_compiled_output_out_of_its_source_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "Cargo.lock").write_text("locked sources", encoding="utf-8")

    def install(
        *command: str | Path,
        env: dict[str, str] | None = None,
        cwd: Path = ROOT,
    ) -> None:
        assert cwd == source
        assert env is not None
        target = Path(env["CARGO_TARGET_DIR"])
        assert not target.is_relative_to(source)
        assert "--offline" in command
        assert "--locked" in command
        target.mkdir()
        (target / "compiled.o").write_bytes(b"not source")
        binary = (
            tmp_path
            / "pyapp/bin"
            / ("pyapp.exe" if create_executable.WINDOWS else "pyapp")
        )
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"the built launcher")

    monkeypatch.setattr(create_executable, "run", install)
    executable = create_executable.build_pyapp(
        tmp_path / "python.tar.gz", "0.1.0", tmp_path, source
    )
    assert executable.read_bytes() == b"the built launcher"
    archive = tmp_path / "source.tar.xz"
    with tarfile.open(archive, "w:xz") as output:
        output.add(source, arcname="pyapp")
    with tarfile.open(archive) as packed:
        assert packed.getnames() == ["pyapp", "pyapp/Cargo.lock"]


def test_launcher_vendoring_preserves_upstream_target_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream = tmp_path / "upstream"
    (upstream / ".cargo").mkdir(parents=True)
    original = '[target.windows]\nrustflags = ["-C", "target-feature=+crt-static"]\n'
    (upstream / ".cargo/config.toml").write_text(original, encoding="utf-8")

    def download(*_args: object, **_kwargs: object) -> None:
        with tarfile.open(tmp_path / create_executable.PYAPP_SHA256, "w:gz") as out:
            out.add(upstream, arcname=f"pyapp-{create_executable.PYAPP}")

    def vendor(command: list[str], *, cwd: Path, stdout: TextIO, check: bool) -> None:
        assert command == ["cargo", "vendor", "--locked", "vendor"]
        assert check
        assert (
            (cwd / ".cargo/config.toml")
            .read_text(encoding="utf-8")
            .startswith(original)
        )
        stdout.write('[source.crates-io]\nreplace-with = "vendored-sources"\n')

    monkeypatch.setattr(create_executable, "run", download)
    monkeypatch.setattr(create_executable.subprocess, "run", vendor)
    source = create_executable.launcher_sources(tmp_path)
    config = tomllib.loads((source / ".cargo/config.toml").read_text(encoding="utf-8"))
    assert config["target"]["windows"]["rustflags"] == [
        "-C",
        "target-feature=+crt-static",
    ]
    assert config["source"]["crates-io"]["replace-with"] == "vendored-sources"


def test_source_archive_rejects_missing_platforms_and_changed_sources(
    tmp_path: Path,
) -> None:
    for machine in ["x86_64", "aarch64"]:
        directory = tmp_path / f"linux-{machine}"
        directory.mkdir()
        source = directory / "library-1.0.src.rpm"
        source.write_bytes(b"the verified source")
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "packages": [
                        {
                            "source": source.name,
                            "sha256": linux_sources.digest(source),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        if machine == "x86_64":
            with pytest.raises(FileNotFoundError):
                linux_sources.verify(tmp_path)
    linux_sources.verify(tmp_path)
    source.write_bytes(b"a different source")
    with pytest.raises(ValueError, match="retained source changed"):
        linux_sources.verify(tmp_path)


@pytest.mark.parametrize("fault", ["", "version", "signature"])
def test_only_the_installed_librarys_verified_source_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    source = "llvm-20.1.8-1.el8.src.rpm"
    wheel = tmp_path / "wheel.whl"
    wheel.write_bytes(b"the wheel")
    monkeypatch.setattr(linux_sources, "bundled_packages", lambda _: set())
    monkeypatch.setattr(linux_sources.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(
        linux_sources.platform, "freedesktop_os_release", lambda: {"ID": "almalinux"}
    )

    def output(*args: str) -> str:
        if "--checksig" in args:
            return "digests OK" if fault == "signature" else "digests signatures OK"
        assert args[-1] == "llvm-static"
        return f"llvm-static 1 20.1.8 1.el8 aarch64 {source}"

    def download(
        command: list[str], *, check: bool
    ) -> subprocess.CompletedProcess[str]:
        assert check
        assert command[-1] == source.removesuffix(".rpm")
        filename = "llvm-21.src.rpm" if fault == "version" else source
        (Path(command[-2]) / filename).write_bytes(b"the exact source RPM")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(linux_sources, "output", output)
    monkeypatch.setattr(linux_sources.subprocess, "run", download)
    store = tmp_path / "sources"
    if fault:
        with pytest.raises(
            ValueError, match=r"installed package's source|verified signature"
        ):
            linux_sources.collect(wheel, store)
        assert not list(store.rglob("*.rpm"))
        assert not list(store.rglob("manifest.json"))
    else:
        linux_sources.collect(wheel, store)
        archive = store / "linux-aarch64" / source
        manifest = json.loads(
            archive.with_name("manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["sha256"] == linux_sources.digest(wheel)
        assert manifest["packages"] == [
            {
                "binary": "llvm-static-1:20.1.8-1.el8.aarch64",
                "source": source,
                "sha256": linux_sources.digest(archive),
            }
        ]
