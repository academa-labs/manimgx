"""Reference interpreters retain their verified wheel's identity and adjacent resources."""

import hashlib
import zipfile
from pathlib import Path

import pytest
from tests.integration.corpus.frozen import prepare


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
