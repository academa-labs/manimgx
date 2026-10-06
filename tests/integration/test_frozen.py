"""Reference interpreters retain their verified wheel's identity and adjacent resources."""

import contextlib
import hashlib
import zipfile
from fractions import Fraction
from pathlib import Path

import pytest
from tests.integration.corpus.case import SIZE, Case, Frames
from tests.integration.corpus.frames import Recorder
from tests.integration.corpus.frozen import Movie, dependencies, prepare
from tests.integration.corpus.frozen_probe import compare

import manimgx


def wheel(path: Path, files: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reference_wheel_is_verified_before_any_extraction(tmp_path: Path) -> None:
    path, output = tmp_path / "reference.whl", tmp_path / "prepared"
    wheel(path, {"manimgx/_engine.abi3.so": b"engine"})
    with pytest.raises(ValueError, match="SHA256"):
        prepare(path, "0" * 64, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "outside", ["../outside", "/outside", "C:/outside", "..\\outside"]
)
def test_reference_wheel_members_cannot_escape_the_artifact(
    tmp_path: Path, outside: str
) -> None:
    path, output = tmp_path / "reference.whl", tmp_path / "prepared"
    digest = wheel(path, {"manimgx/_engine.abi3.so": b"engine", outside: b"outside"})
    with pytest.raises(ValueError, match="unsafe wheel member"):
        prepare(path, digest, output)
    assert not output.exists()


def test_native_resources_and_notices_stay_with_the_reference_engine(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reference.whl"
    files = {
        "manimgx/_engine.pyd": b"engine",
        "manimgx/dxcompiler.dll": b"compiler",
        "manimgx/lavapipe/libvulkan_lvp.so": b"driver",
        "manimgx-0.1.0.dist-info/licenses/LICENSE-THIRD-PARTY": b"notices",
    }
    output = prepare(path, wheel(path, files), tmp_path / "prepared")
    assert {name: (output / name).read_bytes() for name in files} == files


def test_a_new_reference_cannot_inherit_stale_native_resources(tmp_path: Path) -> None:
    path, output = tmp_path / "reference.whl", tmp_path / "prepared"
    output.mkdir()
    stale = output / "dxcompiler.dll"
    stale.write_bytes(b"another compiler")
    digest = wheel(path, {"manimgx/_engine.pyd": b"verified engine"})
    with pytest.raises(ValueError, match="directory must be empty"):
        prepare(path, digest, output)
    assert list(output.iterdir()) == [stale]
    assert stale.read_bytes() == b"another compiler"


@pytest.mark.parametrize("engines", [[], ["_engine.abi3.so", "_engine.pyd"]])
def test_a_reference_wheel_identifies_exactly_one_native_module(
    tmp_path: Path, engines: list[str]
) -> None:
    path = tmp_path / "reference.whl"
    digest = wheel(path, {f"manimgx/{name}": b"engine" for name in engines})
    with pytest.raises(ValueError, match="one native engine"):
        prepare(path, digest, tmp_path / "prepared")


def test_dependency_changes_cannot_silently_change_the_reference(
    tmp_path: Path,
) -> None:
    old, current = tmp_path / "old.lock", tmp_path / "uv.lock"
    old.write_bytes(b"numpy=2.5.3\n")
    current.write_bytes(old.read_bytes())
    assert dependencies(old, current) == hashlib.sha256(old.read_bytes()).hexdigest()
    current.write_bytes(b"numpy=2.6\n")
    with pytest.raises(ValueError, match="frozen dependencies"):
        dependencies(old, current)


@pytest.mark.parametrize("negative", [False, True])
def test_frozen_package_uses_the_existing_isolated_runner(
    tmp_path: Path, negative: bool
) -> None:
    case = Case("basic_usage")
    unchanged = [
        path.read_bytes()
        for path in (case.scene, case.facts_path, case.video_hash("manimgx"))
    ]
    package = Path(manimgx.__file__).resolve().parent.parent
    result = compare(case, package, tmp_path, negative=negative)
    assert result["status"] == ("different" if negative else "exact"), result
    assert result["same_frame_count"]
    assert result["same_duration"]
    assert result["same_timeline"]
    assert (result["changed_frames"] != 0) is negative
    assert all(
        (tmp_path / name).is_file()
        for name in ("reference.log", "actual.log", "reference.mkv")
    )
    assert unchanged == [
        path.read_bytes()
        for path in (case.scene, case.facts_path, case.video_hash("manimgx"))
    ]


def test_a_changed_scene_cannot_become_its_own_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Case, "facts", lambda _: None)
    result = compare(Case("basic_usage"), tmp_path, tmp_path)
    assert result["status"] == "error"
    assert result["error"] == "the scene source differs from its canonical facts"


@pytest.mark.parametrize("expected_count", [1, 2, 3])
def test_reference_movie_must_decode_exactly_its_recorded_frames(
    tmp_path: Path, expected_count: int
) -> None:
    path = tmp_path / "reference.mkv"
    pixels = bytes(SIZE[0] * SIZE[1] * 3)
    recorder = Recorder(SIZE, 10, path)
    recorder.add(pixels, 2)
    recorder.close()
    facts = Frames(
        (("unused", expected_count),), Fraction(1), ((Fraction(0), expected_count),)
    )
    with contextlib.closing(Movie(path, facts)) as movie:

        def read() -> None:
            for frame in range(expected_count):
                assert movie.render(frame) == pixels
            movie.finish()

        if expected_count == 2:
            read()
        else:
            with pytest.raises(ValueError, match="reference movie"):
                read()
