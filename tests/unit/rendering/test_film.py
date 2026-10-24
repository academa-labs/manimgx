"""A film is a row of sections, each beginning at a frame; its captions are those the scene added
and those of its speech, in order.

- A section begins at a frame: after a play that ends between frames, the world holds still
  until the next one (and nothing moves meanwhile), whatever the frame rate. A section with no
  frame gives way to the next; the first begins with the film.
- A section's first frame is sent alone, never merged into the hold before it, as a key.
- Subtitles are the captions in SubRip form, numbered, their times to the millisecond.
"""

import itertools
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING

import numpy as np
import pytest
from hypothesis import HealthCheck, example, given, reject, settings
from hypothesis import strategies as st
from tests.scenes import (
    KINDS,
    MONOTONE,
    SHAPES,
    Leaf,
    Node,
    silence,
    trees,
)

import manimgx as m
from manimgx.audio import Speech, Word
from manimgx.audio.sound import RATE
from manimgx.rendering import feed
from manimgx.rendering.film import Frame
from manimgx.settings import config


def film_of(
    story: Callable[[m.Scene], None],
    fps: float = 10,
    frames: list[Frame] | None = None,
) -> m.Film:
    class Made(m.Scene):
        def construct(self) -> None:
            story(self)

    saved = config.frame_rate
    config.frame_rate = fps
    try:
        return Made().render(frames=None if frames is None else frames.append)
    finally:
        config.frame_rate = saved


class TestSections:
    @settings(max_examples=30)
    @given(
        run_time=st.sampled_from([0.25, 0.55, 1.0, 1.37]),
        fps=st.sampled_from([10, 24, 30, 60]),
    )
    def test_a_section_begins_at_a_frame(self, run_time: float, fps: int) -> None:
        def construct(self: m.Scene) -> None:
            self.play(m.FadeIn(m.Dot()), run_time=run_time)
            self.next_section("next", notes="go on")
            self.play(m.FadeOut(m.Dot()))

        film = film_of(construct, fps)
        first, section = film.sections
        assert (first.name, first.start, first.frame) == ("unnamed", 0, 0)
        assert section.start == Fraction(section.frame, fps)
        assert section.start >= Fraction(run_time).limit_denominator(10**6)
        assert section.start - Fraction(run_time).limit_denominator(10**6) < Fraction(
            1, fps
        )
        assert (section.name, section.notes, section.type) == (
            "next",
            "go on",
            "default.normal",
        )

    def test_the_world_holds_until_the_section_begins(self) -> None:
        dot = m.Dot()

        def construct(self: m.Scene) -> None:
            dot.add_updater(lambda d, dt: d.shift(dt * m.RIGHT))
            self.add(dot)
            self.wait(0.55)
            self.next_section()

        film_of(construct, 10)
        assert dot.get_x() == pytest.approx(
            0.55
        )  # it did not move between 0.55 and 0.6

    def test_a_section_with_no_frame_gives_way(self) -> None:
        def construct(self: m.Scene) -> None:
            self.next_section("a")
            self.next_section("b", "presentation.loop")
            self.play(m.FadeIn(m.Dot()))

        film = film_of(construct)
        assert [(s.name, s.frame, s.type) for s in film.sections] == [
            ("b", 0, "presentation.loop")
        ]

    def test_a_section_begins_with_a_key_frame_of_its_own(self) -> None:
        sent: list[Frame] = []

        def construct(self: m.Scene) -> None:
            self.add(m.Square())
            self.wait(1)  # one hold across the boundary, unless split
            self.next_section("still")
            self.wait(1)

        film = film_of(construct, 10, sent)
        _, still = film.sections
        keys = [f.index for f in sent if f.key]
        assert keys == [still.frame] == [10]


class TestCaptions:
    def test_captions_are_added_and_spoken_in_order(self) -> None:
        speech = Speech(
            np.full(RATE, 0.1, np.float32),
            text="Hello there.",
            words=[Word("Hello", 0.1, 0.4), Word("there.", 0.5, 0.9)],
            rate=RATE,
        )

        def construct(self: m.Scene) -> None:
            self.add_subcaption("first", duration=0.5)
            self.wait(1)
            self.add_sound(speech)
            self.wait(1)

        film = film_of(construct)
        assert [(c.start, c.end, c.text) for c in film.captions()] == [
            (0.0, 0.5, "first"),
            (pytest.approx(1.1), pytest.approx(1.9), "Hello there."),
        ]
        assert film.subtitles().startswith(
            "1\n00:00:00,000 --> 00:00:00,500\nfirst\n\n2\n00:00:01,100 -->"
            " 00:00:01,900\n"
        )
        assert film_of(lambda self: self.wait(1)).subtitles() == ""  # none, nothing

    def test_the_end_cuts_what_still_sounds(self) -> None:
        long = m.Sound(np.zeros(3 * RATE, np.float32), rate=RATE)

        def story(self: m.Scene) -> None:
            self.add_sound(long)
            self.wait(1)

        film = film_of(story)
        ((clip, lost),) = film.cut()
        assert clip.sound is long
        assert lost == pytest.approx(3 - film.frame_count / 10)


# ── captions ─────────────────────────────────────────────────────────────────────────────
_STAMP = r"\d{2,}:[0-5]\d:[0-5]\d,\d{3}"
_CUE = re.compile(rf"(\d+)\n({_STAMP}) --> ({_STAMP})\n")


def _seconds(stamp: str) -> float:
    hours, minutes, rest = stamp.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


@given(
    captions=st.lists(
        st.tuples(
            st.sampled_from([0.25, 0.5, 1.0]),  # when, in the scene
            st.sampled_from([-1.0, -0.25, 0.0, 0.5]),  # its offset
            st.sampled_from([0.5, 1.0, 2.0]),  # its duration
        ),
        min_size=1,
        max_size=3,
    ),
    spoken=st.sampled_from([None, -0.5, 0.0, 0.25]),
)
def test_a_films_subtitles_are_well_formed_whatever_the_scene_captions(
    captions: list[tuple[float, float, float]], spoken: float | None
) -> None:
    """`manimgx render` writes the film's captions beside its video as SubRip: every cue is
    numbered in order, its times are h:mm:ss,mmm (never negative) and it ends no earlier than
    it begins, whatever offsets the scene captions or speaks with."""

    class Captioned(m.Scene):
        def construct(self) -> None:
            if spoken is not None:
                self.add_sound(silence("hello there"), time_offset=spoken)
            for when, offset, duration in captions:
                self.wait(when)
                self.add_subcaption("a caption", duration=duration, offset=offset)

    film = Captioned().render()
    subtitles = film.subtitles()
    cues = subtitles.strip().split("\n\n") if subtitles else []
    for k, cue in enumerate(cues, 1):
        found = _CUE.match(cue + "\n")
        assert found is not None, f"cue {k} is not SubRip: {cue!r}"
        assert int(found[1]) == k
        assert 0 <= _seconds(found[2]) <= _seconds(found[3])
        assert _seconds(found[3]) <= round(float(film.frame_count / film.fps), 3)


@given(content=st.text("ab \n\r\t", max_size=40))
def test_caption_whitespace_cannot_create_an_extra_subtitle_cue(content: str) -> None:
    """Blank lines and empty captions never become cue separators inside a subtitle."""

    class Captioned(m.Scene):
        def construct(self) -> None:
            self.add_subcaption(content, duration=0.5)
            self.wait(1)

    subtitles = Captioned().render().subtitles()
    cues = subtitles.strip().split("\n\n") if subtitles else []
    if content.strip():
        assert len(cues) == 1
        found = _CUE.match(cues[0])
        assert found is not None
        assert found[1] == "1"
        assert cues[0][found.end() :].split() == content.split()
    else:
        assert not cues


# ── current values and held pictures ─────────────────────────────────────────────────────
if TYPE_CHECKING:
    pass

pytestmark = pytest.mark.filterwarnings("error")

LAWS = settings(
    max_examples=100,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
FPS = 10


@dataclass(frozen=True)
class Picture:
    """A picture of a film as its take holds it: shown `repeat` frames, through `view`, drawing
    `records` (bytes, `feed.RECORD` each)."""

    repeat: int
    view: bytes
    records: bytes


def take(
    tell: Callable[[m.Scene], None], fps: int = FPS
) -> list[Picture] | type[Exception]:
    """The film of `tell` as a take: its pictures; or the kind of error it raises (a story may
    ask the impossible, as two replacements of one mobject in one play)."""
    pictures: list[Picture] = []
    send = m.Film._send

    def sent(film: m.Film) -> None:
        if film._pending is not None:
            view, records, _, repeat = film._pending
            pictures.append(Picture(repeat, view, records))
        send(film)

    class Told(m.Scene):
        def construct(self) -> None:
            tell(self)

    saved = config.frame_rate
    config.frame_rate = fps
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(m.Film, "_send", sent)
            Told().render(take=lambda chunk: None)
    except ValueError as error:
        return type(error)
    finally:
        config.frame_rate = saved
    return pictures


KEYS = (
    "key1",
    "key2",
    "fill_rows",
    "stroke_rows",
    "fill_rows2",
    "stroke_rows2",
    "texture",
)
NUMBERS = tuple(
    name for name in feed.RECORD.names or () if name not in (*KEYS, "flags")
)


def meaning(records: bytes) -> np.ndarray:
    """Records as what they draw, written one way: a morph between two placements of one shape
    is one placement of it (the terms' matrices add); a paint mixed with itself is itself (no
    mix)."""
    r = np.frombuffer(records, feed.RECORD).copy()
    one = (r["key2"] != 0) & (r["key2"] == r["key1"])
    r["m1"][one] += r["m2"][one]
    r["key2"][one] = 0
    r["m2"][r["key2"] == 0] = 0.0
    # a paint mixed in by nothing draws nothing; mixed in wholly, it is the paint
    for unmixed, kept, lost in (
        (r["dash"][:, 3] <= 0, "", "2"),
        (r["dash"][:, 3] >= 1, "2", ""),
    ):
        for name in ("fill", "stroke", "background", "fill_rows", "stroke_rows"):
            r[name + lost][unmixed] = r[name + kept][unmixed]
    same = (
        (r["fill"] == r["fill2"]).all(axis=1)
        & (r["stroke"] == r["stroke2"]).all(axis=1)
        & (r["background"] == r["background2"]).all(axis=1)
        & (r["fill_rows"] == r["fill_rows2"])
        & (r["stroke_rows"] == r["stroke_rows2"])
    )
    r["dash"][same, 3] = 0.0
    return r


def unlike(a: np.ndarray, b: np.ndarray) -> str | None:
    """How two frames' records differ in what they draw (None: alike): the same shapes,
    brushes, textures and flags, and their numbers alike but for rounding."""
    if len(a) != len(b):
        return f"{len(a)} records, not {len(b)}"
    for k in range(len(a)):
        for name in (*KEYS, "flags"):
            if a[k][name] != b[k][name]:
                return f"record {k}: {name} {a[k][name]:#x} vs {b[k][name]:#x}"
        for name in NUMBERS:
            x, y = np.asarray(a[k][name], float), np.asarray(b[k][name], float)
            if not np.allclose(x, y, rtol=1e-5, atol=1e-5):
                return f"record {k}: {name} {np.round(x, 4).tolist()} vs {np.round(y, 4).tolist()}"
    return None


LOOKS: dict[str, Callable[[m.Mobject], object]] = {
    "plain": lambda mob: mob,
    "graded fill": lambda mob: mob.set_fill([m.RED, m.BLUE], opacity=1),
    "graded stroke": lambda mob: mob.set_stroke([m.YELLOW, m.TEAL], width=6),
    "sheen": lambda mob: mob.set_sheen(0.4, m.UR),
}


@dataclass
class Looked:
    """A stage of shapes, each with a look, some added, then plays of animation trees."""

    stage: list[tuple[str, str]]
    added: list[bool]
    plays: list[list[Leaf | Node]] = field(default_factory=list)

    def tell(self, scene: m.Scene) -> None:
        stage: list[m.Mobject] = []
        for i, (shape, look) in enumerate(self.stage):
            mob = SHAPES[shape]().shift([i - 2.0, 0.5 * (i % 2), 0])
            LOOKS[look](mob)
            stage.append(mob)
        scene.add(*(mob for mob, added in zip(stage, self.added, strict=True) if added))
        for play in self.plays:
            scene.play(*(tree.build(stage) for tree in play))


@st.composite
def looked(draw: st.DrawFn) -> Looked:
    """1 to 3 shapes with looks, some added, and 1 to 2 plays of 1 to 2 animation trees."""
    stage = draw(
        st.lists(
            st.tuples(st.sampled_from(sorted(SHAPES)), st.sampled_from(sorted(LOOKS))),
            min_size=1,
            max_size=3,
        )
    )
    added = draw(st.lists(st.booleans(), min_size=len(stage), max_size=len(stage)))
    plays = draw(
        st.lists(
            st.lists(trees(len(stage), MONOTONE, KINDS), min_size=1, max_size=2),
            min_size=1,
            max_size=2,
        )
    )
    return Looked(stage, added, plays)


@LAWS
@example(
    story=Looked([("circle", "plain")], [True], [[Leaf("shift", 0, v=(0.0, 0.0))]]),
)
@example(
    story=Looked(
        [("circle", "graded fill")],
        [False],
        [
            [
                Node(
                    "group",
                    [
                        Leaf("transform", 0, v=(0.0, 0.0)),
                        Leaf("shift", 0, v=(0.0, 0.0)),
                    ],
                    lag=0.25,
                )
            ]
        ],
    ),
)
@given(story=looked())
def test_a_frame_that_shows_nothing_new_lengthens_the_one_before(story: Looked) -> None:
    """A frame equal to the one before is not sent again but lengthens it (a hold): no two
    pictures in a row of a film draw the same through the same view."""
    film = take(story.tell)
    if not isinstance(film, list):
        reject()
    for k, (a, b) in enumerate(itertools.pairwise(film)):
        same = (
            a.view == b.view
            and meaning(a.records).tobytes() == meaning(b.records).tobytes()
        )
        assert not same, (
            f"pictures {k} and {k + 1} draw the same: two pictures, not one"
        )


def _image() -> m.ImageMobject:
    pixels = np.zeros((4, 4, 4), np.uint8)
    pixels[..., 0], pixels[..., 3] = np.arange(16).reshape(4, 4) * 16, 255
    return m.ImageMobject(pixels)


MADE: dict[str, Callable[[], m.Mobject]] = {
    "square": lambda: m.Square(1.2, fill_opacity=0.5),
    "circle": lambda: m.Circle(0.7),
    "arrow": lambda: m.Arrow(m.LEFT, m.RIGHT),
    "dot": lambda: m.Dot(),
    "image": _image,
}
COLORS = [m.RED, m.YELLOW, m.TEAL]


def _paint(
    change: Callable[[m.VMobject, float], object],
) -> Callable[[m.Mobject, float], object]:
    """A change of a path's paint (nothing, for another kind)."""
    return lambda mob, x: change(mob, x) if isinstance(mob, m.VMobject) else None


CHANGES: dict[str, Callable[[m.Mobject, float], object]] = {
    "shift": lambda mob, x: mob.shift((0.5 + x) * m.RIGHT),
    "scale": lambda mob, x: mob.scale(0.5 + x),
    "rotate": lambda mob, x: mob.rotate(0.3 + x),
    "stretch": lambda mob, x: mob.stretch(1.5 + x, 1),
    "opacity": lambda mob, x: mob.set_opacity(x),
    "color": _paint(lambda mob, x: mob.set_color(COLORS[int(3 * x) % 3])),
    "graded fill": _paint(lambda mob, x: mob.set_fill([m.RED, m.BLUE], opacity=1)),
    "stroke width": _paint(lambda mob, x: mob.set_stroke(width=1 + 8 * x)),
    "sheen": _paint(lambda mob, x: mob.set_sheen(0.2 + x / 2, m.UR)),
    "sheen direction": _paint(
        lambda mob, x: mob.set_sheen_direction(m.UR if x < 0.5 else m.DOWN)
    ),
    "add a member": lambda mob, x: mob.add(m.Dot((1 + 2 * x) * m.UP)),
    "z index": lambda mob, x: mob.set_z_index(x),
    "resampling": lambda mob, x: (
        mob.set_resampling_algorithm(m.RESAMPLING_ALGORITHMS["nearest"])
        if isinstance(mob, m.ImageMobject)
        else None
    ),
}


@dataclass
class Shown:
    """A stage of mobjects with looks, related (`member`: stage[j] joins stage[i]'s family;
    `frame`: stage[i]'s gradients span stage[j]), shown, then changed."""

    stage: list[tuple[str, str]]
    relations: list[tuple[str, int, int]]
    changes: list[tuple[str, int, float]]

    def build(self) -> tuple[list[m.Mobject], list[m.Mobject]]:
        """The stage, and the mobjects the scene holds (those of no other's family)."""
        stage: list[m.Mobject] = []
        for kind, look in self.stage:
            mob = MADE[kind]()
            if isinstance(mob, m.VMobject):
                LOOKS[look](mob)
            stage.append(mob)
        n, members = len(stage), set()
        for relation, i, j in self.relations:
            i, j = sorted((i % n, j % n))
            if i == j:
                continue
            if relation == "member":
                try:
                    stage[i].add(stage[j])
                except TypeError:  # (a kind that cannot hold the other's)
                    continue
                members.add(j)
            elif isinstance(mob := stage[i], m.VMobject):
                mob.gradient_frame = stage[j]
        return stage, [mob for k, mob in enumerate(stage) if k not in members]

    def change(self, stage: list[m.Mobject]) -> None:
        for name, i, x in self.changes:
            CHANGES[name](stage[i % len(stage)], x)


@st.composite
def shown(draw: st.DrawFn) -> Shown:
    """1 to 3 mobjects with looks, up to 2 relations between them, and 1 to 3 changes."""
    stage = draw(
        st.lists(
            st.tuples(st.sampled_from(sorted(MADE)), st.sampled_from(sorted(LOOKS))),
            min_size=1,
            max_size=3,
        )
    )
    index = st.integers(0, len(stage) - 1)
    relations = draw(
        st.lists(
            st.tuples(st.sampled_from(["member", "frame"]), index, index), max_size=2
        )
    )
    changed = draw(
        st.lists(
            st.tuples(
                st.sampled_from(sorted(CHANGES)),
                index,
                st.sampled_from([0.0, 0.3, 0.7, 1.0]),
            ),
            min_size=1,
            max_size=3,
        )
    )
    return Shown(stage, relations, changed)


def last_picture(story: Shown, changed_after_shown: bool) -> bytes:
    """The records of a film's last picture: its stage shown for a frame and changed, or
    changed before it is first shown, and shown."""

    def tell(scene: m.Scene) -> None:
        stage, held = story.build()
        if not changed_after_shown:
            story.change(stage)
        scene.add(*held)
        scene.wait(1 / FPS)
        if changed_after_shown:
            story.change(stage)
        scene.wait(1 / FPS)

    film = take(tell)
    assert isinstance(film, list)
    return film[-1].records


@LAWS
@example(story=Shown([("arrow", "graded fill")], [], [("add a member", 0, 0.0)]))
@example(
    story=Shown(
        [("square", "graded fill"), ("dot", "plain")],
        [("frame", 0, 1)],
        [("shift", 1, 0.7)],
    )
)
@example(story=Shown([("image", "plain")], [], [("resampling", 0, 0.0)]))
@given(story=shown())
def test_a_frame_shows_its_mobjects_as_they_are_now(story: Shown) -> None:
    """A frame's records are a function of what its mobjects show now: a mobject changed after
    it was first shown is drawn as the same mobject changed before it was ever shown, exactly.
    Whatever a change touches (points, paint, a member, the box a gradient spans, how an image
    is sampled), what was made of the mobject before does not survive it."""
    after = meaning(last_picture(story, changed_after_shown=True))
    before = meaning(last_picture(story, changed_after_shown=False))
    difference = unlike(after, before)
    assert difference is None, f"changed after shown, then drawn: {difference}"
    assert after.tobytes() == before.tobytes(), "the same, but not to the bit"


_UNDRAWN = r"""
import ctypes, json, sys, time

import numpy as np

import manimgx as m
from manimgx.rendering import feed

keep, sweep, shapes = (int(a) for a in sys.argv[1:4])
feed.KEEP, feed.SWEEP, feed.MARK = keep, sweep, 1  # the film forgets what it showed, soon


class Shapes(m.Scene):
    def construct(self) -> None:
        for k in range(shapes):
            shape = m.RegularPolygon(3 + k)
            self.add(shape)
            self.wait(0.2)
            self.remove(shape)
        for _ in range(keep + sweep + 1):
            self.wait(0.1)


film = Shapes().render()  # no video, no frames: nothing is drawn
player = film._player
if player is not None:
    held = player.held()
    player.add_rows(0x5EED, np.ones((1 << 16, 4), "<f4").tobytes())
    deadline = time.monotonic() + 60
    while player.held() <= held and time.monotonic() < deadline:
        time.sleep(0.01)
if sys.platform == "darwin":  # a GPU's driver loads as the GPU is brought up
    dyld = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    dyld._dyld_image_count.restype = ctypes.c_uint32
    dyld._dyld_get_image_name.restype = ctypes.c_char_p
    dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    names = [dyld._dyld_get_image_name(i) or b"" for i in range(dyld._dyld_image_count())]
    up = any(name.startswith(b"/System/Library/Extensions/") for name in names)
else:
    with open("/proc/self/maps") as maps:
        up = "libvulkan" in maps.read()
print(json.dumps({"evictions": film.feeder.evictions, "gpu": up}))
"""
