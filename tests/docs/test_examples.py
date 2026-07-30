"""The docs' examples, as the site's build renders them (`docs/examples.py`): the build has
no voice's key (its workflow has none), so a narrated example says what `docs/voice/` keeps."""

import pytest
from docs import examples


def test_a_narrated_example_says_what_docs_voice_keeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAL_KEY", raising=False)
    narrated = [e for e in examples.examples() if ".say(" in e.code]
    assert narrated
    for example in narrated:
        examples.load(example)().render()  # its frames counted, not drawn
