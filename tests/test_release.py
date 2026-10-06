"""A pending PyPI publisher identifies one project by its workflow and environment.
The release must route only that project's distributions to it, and publish the fonts
before anything that installs manimgx from PyPI.
"""

import json
import subprocess
import tomllib
import zipfile
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml
from scripts.release import linux_sources, smoke_test

ROOT = Path(__file__).parents[1]
JOBS = yaml.safe_load((ROOT / ".github/workflows/release.yaml").read_text())["jobs"]


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
    wheel = yaml.safe_load((ROOT / ".github/workflows/create-wheels.yaml").read_text())[
        "jobs"
    ]["wheel"]
    assert wheel["defaults"]["run"]["shell"] == "bash"
    build = next(step for step in wheel["steps"] if "PLATFORM" in step.get("env", {}))
    assert "${PLATFORM}" in build["run"]


@pytest.mark.parametrize("package", ["manimgx-fonts", "manimgx-fonts-cjk"])
def test_font_artifacts_contain_only_their_own_package(
    package: str, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    expected = set()
    for manifest in sorted((ROOT / "fonts").glob("*/pyproject.toml")):
        project = tomllib.loads(manifest.read_text())["project"]
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
            (ROOT / ".github/workflows/create-wheels.yaml").read_text()
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
    assert JOBS["sdist"]["needs"] == "wheels"
    download = next(
        step["with"]
        for step in JOBS["sdist"]["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert download["pattern"] == "sources-linux-*"


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
            )
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
        manifest = json.loads(archive.with_name("manifest.json").read_text())
        assert manifest["sha256"] == linux_sources.digest(wheel)
        assert manifest["packages"] == [
            {
                "binary": "llvm-static-1:20.1.8-1.el8.aarch64",
                "source": source,
                "sha256": linux_sources.digest(archive),
            }
        ]
