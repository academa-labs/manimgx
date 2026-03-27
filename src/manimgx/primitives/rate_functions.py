"""Rate functions for animation easing.

Every rate function maps [0, 1] -> [0, 1] and is pure Python (no numpy).

There are three kinds of public symbols:

* **Rate functions** — ``(float) -> float``, usable directly as ``rate_func=...``.
* **Combinators** — take a rate function (and parameters) and *return* a new rate
  function.  ``scaled_func``, ``squished_func``.
* **The type alias** ``RateFunc = Callable[[float], float]``.
"""

import math
from collections.abc import Callable

type RateFunc = Callable[[float], float]


# ── Helpers ───────────────────────────────────────────────────────────


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _smooth_with_inflection(t: float, inflection: float) -> float:
    error = _sigmoid(-inflection / 2)
    return min(max((_sigmoid(inflection * (t - 0.5)) - error) / (1 - 2 * error), 0), 1)


def _bounce_out(t: float) -> float:
    if t < 4 / 11:
        return 121 * t * t / 16
    if t < 8 / 11:
        return (363 / 40) * t * t - (99 / 10) * t + 17 / 5
    if t < 9 / 10:
        return (4356 / 361) * t * t - (35442 / 1805) * t + 16061 / 1805
    return (54 / 5) * t * t - (513 / 25) * t + 268 / 25


# ── Core ──────────────────────────────────────────────────────────────


def linear(t: float) -> float:
    return t


def smooth(t: float) -> float:
    return _smooth_with_inflection(t, 10.0)


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 3 * t**2 - 2 * t**3


def smootherstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 6 * t**5 - 15 * t**4 + 10 * t**3


# ── Utility ───────────────────────────────────────────────────────────


def rush_into(t: float) -> float:
    return 2 * _smooth_with_inflection(t / 2.0, 10.0)


def rush_from(t: float) -> float:
    return 2 * _smooth_with_inflection(t / 2.0 + 0.5, 10.0) - 1


def slow_into(t: float) -> float:
    return (1 - (1 - t) * (1 - t)) ** 0.5


def double_smooth(t: float) -> float:
    if t < 0.5:
        return 0.5 * smooth(2 * t)
    return 0.5 * (1 + smooth(2 * t - 1))


# ── Oscillating ───────────────────────────────────────────────────────


def there_and_back(t: float) -> float:
    new_t = 2 * t if t < 0.5 else 2 * (1 - t)
    return smooth(new_t)


def there_and_back_with_pause(t: float, pause_ratio: float = 1.0 / 3) -> float:
    a = (1.0 - pause_ratio) / 2.0
    if t < a:
        return smooth(t / a)
    if t < 1 - a:
        return 1.0
    return smooth((1 - t) / a)


def wiggle(t: float, wiggles: float = 2.0) -> float:
    return there_and_back(t) * math.sin(wiggles * math.pi * t)


# ── Special ───────────────────────────────────────────────────────────


def running_start(t: float, pull_factor: float = -0.5) -> float:
    return (1 - t) * pull_factor * t + t * (1 - (1 - t) * pull_factor) * t


def lingering(t: float) -> float:
    return smooth(1 - (1 - t) ** 3)


def exponential_decay(t: float, half_life: float = 0.1) -> float:
    return 1 - 2 ** (-t / half_life)


# ── Combinators ──────────────────────────────────────────────────────
#
# These are NOT rate functions themselves — they take a rate function (and
# parameters) and *return* a new rate function.


def scaled_func(func: RateFunc = smooth, proportion: float = 0.7) -> RateFunc:
    def result(t: float) -> float:
        return proportion * func(t)

    return result


def squished_func(func: RateFunc, a: float = 0.4, b: float = 0.6) -> RateFunc:
    def result(t: float) -> float:
        if a == b:
            return a
        if t < a:
            return func(0)
        if t > b:
            return func(1)
        return func((t - a) / (b - a))

    return result


# ── Standard easings ─────────────────────────────────────────────────


def ease_in_sine(t: float) -> float:
    return 1 - math.cos(t * math.pi / 2)


def ease_out_sine(t: float) -> float:
    return math.sin(t * math.pi / 2)


def ease_in_out_sine(t: float) -> float:
    return -(math.cos(math.pi * t) - 1) / 2


def ease_in_quad(t: float) -> float:
    return t * t


def ease_out_quad(t: float) -> float:
    return 1 - (1 - t) ** 2


def ease_in_out_quad(t: float) -> float:
    if t < 0.5:
        return 2 * t * t
    return 1 - (-2 * t + 2) ** 2 / 2


def ease_in_cubic(t: float) -> float:
    return t**3


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4 * t**3
    return 1 - (-2 * t + 2) ** 3 / 2


def ease_in_quart(t: float) -> float:
    return t**4


def ease_out_quart(t: float) -> float:
    return 1 - (1 - t) ** 4


def ease_in_out_quart(t: float) -> float:
    if t < 0.5:
        return 8 * t**4
    return 1 - (-2 * t + 2) ** 4 / 2


def ease_in_quint(t: float) -> float:
    return t**5


def ease_out_quint(t: float) -> float:
    return 1 - (1 - t) ** 5


def ease_in_out_quint(t: float) -> float:
    if t < 0.5:
        return 16 * t**5
    return 1 - (-2 * t + 2) ** 5 / 2


def ease_in_expo(t: float) -> float:
    if t == 0:
        return 0.0
    return 2.0 ** (10 * t - 10)


def ease_out_expo(t: float) -> float:
    if t == 1:
        return 1.0
    return 1 - 2.0 ** (-10 * t)


def ease_in_out_expo(t: float) -> float:
    if t == 0:
        return 0.0
    if t == 1:
        return 1.0
    if t < 0.5:
        return 2.0 ** (20 * t - 10) / 2
    return (2 - 2.0 ** (-20 * t + 10)) / 2


def ease_in_circ(t: float) -> float:
    return 1 - math.sqrt(1 - t * t)


def ease_out_circ(t: float) -> float:
    return math.sqrt(1 - (t - 1) ** 2)


def ease_in_out_circ(t: float) -> float:
    if t < 0.5:
        return (1 - math.sqrt(1 - (2 * t) ** 2)) / 2
    return (math.sqrt(1 - (-2 * t + 2) ** 2) + 1) / 2


def ease_in_back(t: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return c3 * t**3 - c1 * t**2


def ease_out_back(t: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_in_out_back(t: float) -> float:
    c1 = 1.70158
    c2 = c1 * 1.525
    if t < 0.5:
        return ((2 * t) ** 2 * ((c2 + 1) * 2 * t - c2)) / 2
    return ((2 * t - 2) ** 2 * ((c2 + 1) * (2 * t - 2) + c2) + 2) / 2


def ease_in_elastic(t: float) -> float:
    if t == 0:
        return 0.0
    if t == 1:
        return 1.0
    c4 = (2 * math.pi) / 3
    return -(2.0 ** (10 * t - 10)) * math.sin((t * 10 - 10.75) * c4)


def ease_out_elastic(t: float) -> float:
    if t == 0:
        return 0.0
    if t == 1:
        return 1.0
    c4 = (2 * math.pi) / 3
    return 2.0 ** (-10 * t) * math.sin((t * 10 - 0.75) * c4) + 1


def ease_in_out_elastic(t: float) -> float:
    if t == 0:
        return 0.0
    if t == 1:
        return 1.0
    c5 = (2 * math.pi) / 4.5
    if t < 0.5:
        return -(2.0 ** (20 * t - 10) * math.sin((20 * t - 11.125) * c5)) / 2
    return (2.0 ** (-20 * t + 10) * math.sin((20 * t - 11.125) * c5)) / 2 + 1


def ease_in_bounce(t: float) -> float:
    return 1 - _bounce_out(1 - t)


def ease_out_bounce(t: float) -> float:
    return _bounce_out(t)


def ease_in_out_bounce(t: float) -> float:
    if t < 0.5:
        return (1 - _bounce_out(1 - 2 * t)) / 2
    return (1 + _bounce_out(2 * t - 1)) / 2
