"""Parts are matched in their own order, so a matching is the same in every run.

- `get_shape_map` gathers a mobject's parts by their keys: the keys in the order each first
  comes, and under each key its parts, each once, at its last place.

(That making a matching changes none of the mobjects it is given, their saved states included,
is a law of every animation: `test_timeline.py`'s registry laws.)
"""

from collections.abc import Hashable

from hypothesis import given
from hypothesis import strategies as st

import manimgx as m
from manimgx.animation.matching import TransformMatchingAbstractBase


class Token(m.Mobject):
    def __init__(self, value: int) -> None:
        super().__init__()
        self.value = value


class Matcher(TransformMatchingAbstractBase):
    """Matches tokens by their values, modulo 3."""

    @staticmethod
    def get_mobject_parts(mobject: m.Mobject) -> list[m.Mobject]:
        return mobject.submobjects

    @staticmethod
    def get_mobject_key(mobject: m.Mobject) -> Hashable:
        assert isinstance(mobject, Token)
        return mobject.value % 3


@given(indices=st.lists(st.integers(0, 8), max_size=50))
def test_parts_are_gathered_by_key_in_their_own_order(indices: list[int]) -> None:
    tokens = [Token(i) for i in range(9)]
    source = m.Mobject()
    source.submobjects = [tokens[i] for i in indices]
    groups = Matcher(m.Mobject(), m.Mobject()).get_shape_map(source)
    assert list(groups) == list(dict.fromkeys(i % 3 for i in indices))
    for key, group in groups.items():
        last = {i: p for p, i in enumerate(indices)}  # each token's last place
        expected = sorted({i for i in indices if i % 3 == key}, key=last.__getitem__)
        assert [id(x) for x in group.submobjects] == [id(tokens[i]) for i in expected]
