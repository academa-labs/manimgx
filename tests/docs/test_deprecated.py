"""Deprecation decorators belong to Python definitions, not native descriptors."""

from pathlib import Path

import griffe
from docs import deprecated


def test_native_properties_have_no_python_getter_to_parse(tmp_path: Path) -> None:
    library = tmp_path / "_engine.pyd"
    library.write_bytes(b"\x00\xffnative code")
    module = griffe.Module("_engine", filepath=library)
    prop = griffe.Attribute("frames", parent=module)
    prop.labels.add("property")
    assert not deprecated.deprecated(prop)
