"""Render a scene with an installed manimgx: the check a built wheel or executable passes
before it is kept.

`python scripts/release/smoke_test.py` runs this Python's manimgx (`python -m manimgx`);
`python scripts/release/smoke_test.py PATH/TO/manimgx` runs that executable;
`python scripts/release/smoke_test.py --take` records the scene as a take in this process (the
browser's wheel: Pyodide has no GPU, and starts no process); the browser's wheel's engine
carries the player for a page, and the fonts its face is set in.
"""

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SCENE = """
import io
import wave

import manimgx as m
import numpy as np


class Smoke(m.Scene):
    def construct(self) -> None:
        # Generate a PCM file, so the installed native decoder (not the array shortcut)
        # supplies the sound which the export must encode as AAC.
        pcm = np.tile(np.array([0, 8192, 0, -8192], dtype="<i2"), 1200)
        wav = io.BytesIO()
        with wave.open(wav, "wb") as out:
            out.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            out.writeframes(pcm.tobytes())
        sound = m.Sound(wav.getvalue())
        np.testing.assert_array_equal(sound.samples[:, 0], pcm / 32768)
        self.add_sound(sound)
        # The linked reference Opus decoder must run on every wheel target, too.
        opus = m.Sound(OPUS_BYTES).samples
        assert opus.shape == (960, 1)
        assert np.isfinite(opus).all() and (abs(opus) < 1e-6).all()
        self.play(m.Write(m.Text("manimgx")))
"""


def scene_source() -> str:
    opus = Path(__file__).resolve().parents[2] / "rust/ffmpeg/tests/silence.opus"
    return SCENE.replace("OPUS_BYTES", repr(opus.read_bytes()))


def main() -> None:
    if sys.argv[1:] == ["--take"]:
        return take()
    manimgx = sys.argv[1:] or [sys.executable, "-m", "manimgx"]
    with tempfile.TemporaryDirectory() as directory:
        scene = Path(directory) / "smoke.py"
        scene.write_text(scene_source(), encoding="utf-8")
        subprocess.run([*manimgx, "--version"], check=True)
        subprocess.run([*manimgx, "render", str(scene), "-r", "320x180"], check=True)
        video = scene.with_name("Smoke.mp4")
        if not video.is_file() or video.stat().st_size == 0:
            sys.exit(f"manimgx rendered no video: {video}")
        # Reopen the exported container with the installed audio decoder. This runs
        # through the executable's own Python too, without assuming a host installation.
        scene.write_text(
            "import manimgx as m\nimport numpy as np\n"
            "class Verify(m.Scene):\n"
            "    def construct(self):\n"
            f"        samples = m.Sound({str(video)!r}).samples\n"
            "        assert samples.shape[1] == 1 and len(samples) >= 4800\n"
            "        assert np.isfinite(samples).all() and np.any(samples)\n",
            encoding="utf-8",
        )
        subprocess.run([*manimgx, "check", str(scene)], check=True)


def take() -> None:
    scene: dict[str, object] = {}
    exec(scene_source(), scene)
    chunks: list[bytes] = []
    film = scene["Smoke"]().render(take=chunks.append)  # ty: ignore[call-non-callable]
    if not film.frame_count or not b"".join(chunks):
        sys.exit("manimgx recorded no take")
    validate_take(b"".join(chunks), film.frame_count)
    player()


def validate_take(data: bytes, frames: int) -> None:
    """Check the wire envelope without a GPU; Pyodide has the writer alone."""
    from manimgx import _engine, config

    messages: list[bytes] = []
    at = 0
    while at < len(data):
        (length,) = struct.unpack_from("<I", data, at)
        at += 4
        if not length or at + length > len(data):
            raise ValueError("the recorded take has an incomplete message")
        messages.append(data[at : at + length])
        at += length
    assert struct.unpack("<BIIId", messages[0]) == (
        14,
        _engine.TAKE_VERSION,
        config.pixel_width,
        config.pixel_height,
        config.frame_rate,
    )
    assert messages[-1] == bytes([12, 0]), (
        "the recorded take did not finish successfully"
    )
    assert (
        sum(struct.unpack_from("<I", m, 1)[0] for m in messages if m[0] == 8) == frames
    )
    assert any(m[0] == 10 and m[5:9] == b"RIFF" for m in messages), (
        "the take has no sound"
    )


def player() -> None:
    from manimgx import _engine
    from manimgx.drawing.typesetting import FONTS

    if _engine.web() is None:
        sys.exit("the wheel's engine has no player for a page")
    if not _engine.face_fonts(list(FONTS)):
        sys.exit("the player's face has no fonts")


if __name__ == "__main__":
    main()
