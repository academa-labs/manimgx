"""Render a scene with an installed manimgx: the check a built wheel or executable passes
before it is kept.

`python scripts/release/smoke_test.py` runs this Python's manimgx (`python -m manimgx`);
`python scripts/release/smoke_test.py PATH/TO/manimgx` runs that executable;
`python scripts/release/smoke_test.py --take` records the scene as a take in this process (the
browser's wheel: Pyodide has no GPU, and starts no process); the browser's wheel's engine
carries the player for a page, and the fonts its face is set in.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCENE = """
import manimgx as m


class Smoke(m.Scene):
    def construct(self) -> None:
        self.play(m.Write(m.Text("manimgx")))
"""


def main() -> None:
    if sys.argv[1:] == ["--take"]:
        return take()
    manimgx = sys.argv[1:] or [sys.executable, "-m", "manimgx"]
    with tempfile.TemporaryDirectory() as directory:
        scene = Path(directory) / "smoke.py"
        scene.write_text(SCENE, encoding="utf-8")
        subprocess.run([*manimgx, "--version"], check=True)
        subprocess.run([*manimgx, "render", str(scene), "-r", "320x180"], check=True)
        video = scene.with_name("Smoke.mp4")
        if not video.is_file() or video.stat().st_size == 0:
            sys.exit(f"manimgx rendered no video: {video}")


def take() -> None:
    scene: dict[str, object] = {}
    exec(SCENE, scene)
    chunks: list[bytes] = []
    film = scene["Smoke"]().render(take=chunks.append)  # ty: ignore[call-non-callable]
    if not film.frame_count or not b"".join(chunks):
        sys.exit("manimgx recorded no take")
    player()


def player() -> None:
    from manimgx import _engine
    from manimgx.drawing.typesetting import FONTS

    if _engine.web() is None:
        sys.exit("the wheel's engine has no player for a page")
    if not _engine.face_fonts(list(FONTS)):
        sys.exit("the player's face has no fonts")


if __name__ == "__main__":
    main()
