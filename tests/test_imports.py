"""Optional features do not add their dependencies to the authoring API's startup."""

import json
import subprocess
import sys

OPTIONAL = {
    "urllib.request",
    "http.client",
    "logging",
    "xml.etree.ElementTree",
    "tempfile",
    "importlib.resources",
    "isosurfaces",
    "subprocess",
    "queue",
    "threading",
}


def loaded(statement: str) -> set[str]:
    """The modules a fresh interpreter holds once it has run `statement`."""
    ran = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys, json; {statement}; print(json.dumps(sorted(sys.modules)))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(json.loads(ran.stdout))


def test_importing_the_authoring_api_defers_optional_dependencies() -> None:
    """Importing the package adds none of the network, SVG, window and contour helpers to what
    the interpreter holds by itself (a coverage run's own modules, say)."""
    added = loaded("import manimgx") - loaded("pass")
    assert added.isdisjoint(OPTIONAL), sorted(added & OPTIONAL)
