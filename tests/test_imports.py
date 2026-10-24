"""Optional features do not add their dependencies to the authoring API's startup."""

import json
import subprocess
import sys


def test_importing_the_authoring_api_defers_optional_dependencies() -> None:
    """Importing the package leaves network, SVG, window and contour helpers unloaded."""
    ran = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, json; import manimgx; print(json.dumps(sorted(sys.modules)))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = set(json.loads(ran.stdout))
    assert loaded.isdisjoint(
        {
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
    )
