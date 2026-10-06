"""A reviewed native interpreter, loaded from its verified wheel beside today's engine.

The wheel keeps its native resources and licenses together. It is extracted, never installed:
the reference needs neither an old Python environment nor a second renderer implementation.
"""

import hashlib
import importlib.util
import json
import sys
import types
import zipfile
from pathlib import Path, PurePosixPath
from typing import Protocol, cast


class RecordedFilm(Protocol):
    size: tuple[int, int]
    frames: int
    fps: float
    timeline: list[tuple[int, int]]

    def render(self, frame: int) -> bytes: ...


class NativeInterpreter(Protocol):
    TAKE_VERSION: int

    def Replay(self, take: bytes) -> RecordedFilm: ...

    def adapter_info(self) -> dict[str, str]: ...


def verify(path: Path, sha256: str) -> None:
    """Check an artifact's independently supplied identity before using its contents."""
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != sha256:
        raise ValueError(f"{path.name}: SHA256 {digest}, expected {sha256}")


def prepare(wheel: Path, sha256: str, directory: Path) -> Path:
    """Extract a verified wheel, retaining the native module's adjacent resources."""
    verify(wheel, sha256)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("the reference wheel directory must be empty")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                raise ValueError(f"unsafe wheel member: {name}")
        engines = [
            name
            for name in names
            if PurePosixPath(name).parent == PurePosixPath("manimgx")
            and PurePosixPath(name).name.startswith("_engine.")
            and name.endswith((".so", ".pyd"))
        ]
        if len(engines) != 1:
            raise ValueError(
                f"a reference wheel needs one native engine, found {engines}"
            )
        directory.mkdir(parents=True, exist_ok=True)
        archive.extractall(directory)
    (directory / "reference-wheel.json").write_text(
        json.dumps({"wheel": wheel.name, "sha256": sha256, "engine": engines[0]}),
        encoding="utf-8",
    )
    return directory


def interpreter(directory: Path) -> NativeInterpreter:
    """Load a prepared artifact under its own package name and native global state."""
    metadata = json.loads(
        (directory / "reference-wheel.json").read_text(encoding="utf-8")
    )
    alias = f"_manimgx_reference_{metadata['sha256']}"
    name = f"{alias}._engine"
    if name not in sys.modules:
        package = types.ModuleType(alias)
        package.__path__ = [str(directory / "manimgx")]
        sys.modules[alias] = package
        spec = importlib.util.spec_from_file_location(
            name, directory / metadata["engine"]
        )
        if spec is None or spec.loader is None:
            raise ImportError("the reference wheel has no loadable native module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            for attribute in ("Replay", "TAKE_VERSION", "adapter_info"):
                if not hasattr(module, attribute):
                    raise ImportError(
                        f"the reference engine does not expose {attribute}"
                    )
        except BaseException:
            sys.modules.pop(name, None)
            sys.modules.pop(alias, None)
            raise
    return cast(NativeInterpreter, sys.modules[name])


def same_adapter(
    reference: NativeInterpreter, actual: NativeInterpreter
) -> dict[str, str]:
    """Require the same backend, device and driver before interpreting pixel differences."""
    wanted, found = reference.adapter_info(), actual.adapter_info()
    if wanted != found:
        raise ValueError(
            f"renderers selected different adapters: {wanted!r} != {found!r}"
        )
    return found
