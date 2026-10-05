"""A pending PyPI publisher identifies one project by its workflow and environment.
The release must route only that project's distributions to it, and publish the fonts
before anything that installs manimgx from PyPI.
"""

import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

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
