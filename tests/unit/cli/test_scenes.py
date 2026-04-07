"""Each scene-file load starts from shipped settings, then applies the file's own."""

import sys
from pathlib import Path

import pytest

from manimgx.cli.scenes import load, scene
from manimgx.config import Config, config


@pytest.mark.parametrize("pick_scene", [False, True])
def test_a_loaded_file_starts_from_defaults_and_sets_its_own_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pick_scene: bool
) -> None:
    source = tmp_path / "fresh_cli_source.py"
    source.write_text(
        "import manimgx as m\n"
        "m.config.pixel_width = 640\n"
        "class Only(m.Scene):\n"
        "    pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        for _ in range(2):
            config.pixel_width, config.pixel_height, config.frame_rate = 320, 180, 12
            if pick_scene:
                assert scene(source, None).__name__ == "Only"
            else:
                load(source)
            assert config.pixel_width == 640
            assert config.pixel_height == Config().pixel_height
            assert config.frame_rate == Config().frame_rate
    finally:
        sys.modules.pop(source.stem, None)
