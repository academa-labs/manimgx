"""The docs' examples, as the site's build renders them (`docs/examples.py`): the build has
no voice's key (its workflow has none), so a narrated example says what `docs/voice/` keeps."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from docs import examples


def test_a_broken_runtime_stops_before_workers_start_or_films_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    film = tmp_path / "previous.webp"
    film.write_bytes(b"previous film")
    pool = Mock(side_effect=AssertionError("a broken runtime must not start workers"))
    monkeypatch.setattr(examples, "FILMS", tmp_path)
    monkeypatch.setattr(examples, "ProcessPoolExecutor", pool)
    monkeypatch.setitem(sys.modules, "manimgx", None)

    with pytest.raises(ModuleNotFoundError, match="manimgx"):
        examples.main([])

    pool.assert_not_called()
    assert film.read_bytes() == b"previous film"


def test_a_narrated_example_says_what_docs_voice_keeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAL_KEY", raising=False)
    narrated = [e for e in examples.examples() if ".say(" in e.code]
    assert narrated
    for example in narrated:
        examples.load(example)().render()  # its frames counted, not drawn
