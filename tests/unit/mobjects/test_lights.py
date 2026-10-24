"""A light's numbers are its value, with its point: a tween of a setter carries them, from the
first keyframe's to the last's, and `become` takes them."""

from collections.abc import Callable

import pytest
from tests.scenes import instants

import manimgx as m
from manimgx.animation import easing as rf
from manimgx.mobject import _snapshot
from manimgx.rendering.feed import lighting


@pytest.mark.parametrize(
    ("make", "name", "end"),
    [
        (lambda: m.PointLight(intensity=1.0), "intensity", 3.0),
        (lambda: m.PointLight(radius=20.0), "radius", 5.0),
        (lambda: m.SpotLight(angle=0.5), "angle", 1.0),
        (lambda: m.SpotLight(softness=0.2), "softness", 0.6),
    ],
    ids=["intensity", "radius", "angle", "softness"],
)
def test_a_play_of_a_setter_carries_a_lights_number(
    make: Callable[[], m.Light], name: str, end: float
) -> None:
    light = make()
    start = float(getattr(light, name))

    def construct(s: m.Scene) -> None:
        s.add(light)
        s.play(light.animate(run_time=1, rate_func=rf.linear).set(**{name: end}))

    for t, value in instants(construct, lambda s: float(getattr(light, name))).items():
        assert value == pytest.approx(start + (end - start) * min(float(t), 1.0))


def test_a_light_becomes_another_lights_numbers() -> None:
    light = m.PointLight(intensity=1.0, radius=20.0, color=m.WHITE)
    light.become(m.PointLight(intensity=2.5, radius=4.0, color=m.RED))
    assert (light.intensity, light.radius, light.light_color) == (2.5, 4.0, m.RED)


LIGHTS: dict[str, Callable[[], m.Light]] = {
    "ambient": lambda: m.AmbientLight(color=m.RED, intensity=0.3),
    "sun": lambda: m.SunLight(m.UR, color=m.BLUE, intensity=2.0, shadows=False),
    "point": lambda: m.PointLight(m.UP, intensity=4.0, radius=6.0),
    "spot": lambda: m.SpotLight(
        2 * m.OUT, toward=m.RIGHT, angle=0.4, softness=0.5, shadows=False
    ),
    "environment": lambda: m.EnvironmentLight(intensity=0.7, shadows=False),
}


@pytest.mark.parametrize("kind", LIGHTS)
def test_a_lights_keyframe_lights_as_it_does(kind: str) -> None:
    """A light's value is all its kind is read by (its numbers, whether it casts shadows, its
    picture, where a spot points): a keyframe made of it lights the scene as it does."""
    light = LIGHTS[kind]()
    keyframe = _snapshot(light)
    assert isinstance(keyframe, type(light))
    camera = m.Scene().camera
    assert lighting(camera, [keyframe]) == lighting(camera, [light])


@pytest.mark.parametrize("kind", LIGHTS)
def test_a_light_becomes_another_of_its_kind_whole(kind: str) -> None:
    other = LIGHTS[kind]()
    light = type(other)()
    light.become(other)
    camera = m.Scene().camera
    assert lighting(camera, [light]) == lighting(camera, [other])
