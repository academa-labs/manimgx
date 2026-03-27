import functools
import re
from colorsys import hls_to_rgb
from math import pi as _PI
from typing import Literal


@functools.lru_cache(maxsize=256)
def parse_color(color: str) -> tuple[int, int, int]:
    return _parse_str(color)


_RADS = 2 * _PI

_r_255 = r"(\d{1,3}(?:\.\d+)?)"
_r_comma = r"\s*,\s*"
_r_alpha = r"(?:\d(?:\.\d+)?|\.\d+|\d{1,2}%)"
_r_h = r"(-?\d+(?:\.\d+)?|-?\.\d+)(deg|rad|turn)?"
_r_sl = r"(\d{1,3}(?:\.\d+)?)%"

_RE_HEX_SHORT = re.compile(
    r"\s*(?:#|0x)?([0-9a-f])([0-9a-f])([0-9a-f])(?:[0-9a-f])?\s*"
)
_RE_HEX_LONG = re.compile(
    r"\s*(?:#|0x)?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})(?:[0-9a-f]{2})?\s*"
)
_RE_RGB = re.compile(
    rf"\s*rgba?\(\s*{_r_255}{_r_comma}{_r_255}{_r_comma}{_r_255}"
    rf"(?:{_r_comma}{_r_alpha})?\s*\)\s*"
)
_RE_HSL = re.compile(
    rf"\s*hsla?\(\s*{_r_h}{_r_comma}{_r_sl}{_r_comma}{_r_sl}"
    rf"(?:{_r_comma}{_r_alpha})?\s*\)\s*"
)
_RE_RGB_V4 = re.compile(
    rf"\s*rgba?\(\s*{_r_255}\s+{_r_255}\s+{_r_255}" rf"(?:\s*/\s*{_r_alpha})?\s*\)\s*"
)
_RE_HSL_V4 = re.compile(
    rf"\s*hsla?\(\s*{_r_h}\s+{_r_sl}\s+{_r_sl}" rf"(?:\s*/\s*{_r_alpha})?\s*\)\s*"
)


def _parse_str(value: str) -> tuple[int, int, int]:
    s = value.strip().lower()

    if s in _COLORS_BY_NAME:
        return _COLORS_BY_NAME[s]

    if s == "transparent":
        return (0, 0, 0)

    m = _RE_HEX_SHORT.fullmatch(s)
    if m:
        r, g, b = m.groups()
        return (int(r * 2, 16), int(g * 2, 16), int(b * 2, 16))

    m = _RE_HEX_LONG.fullmatch(s)
    if m:
        r, g, b = m.groups()
        return (int(r, 16), int(g, 16), int(b, 16))

    m = _RE_RGB.fullmatch(s) or _RE_RGB_V4.fullmatch(s)
    if m:
        return _parse_rgb(m.group(1), m.group(2), m.group(3))

    m = _RE_HSL.fullmatch(s) or _RE_HSL_V4.fullmatch(s)
    if m:
        return _parse_hsl(m.group(1), m.group(2), m.group(3), m.group(4))

    msg = f"Invalid color string: {value!r}"
    raise ValueError(msg)


def _parse_rgb(r_s: str, g_s: str, b_s: str) -> tuple[int, int, int]:
    return (
        _parse_channel(float(r_s)),
        _parse_channel(float(g_s)),
        _parse_channel(float(b_s)),
    )


def _parse_channel(v: float) -> int:
    return max(0, min(255, round(v)))


def _parse_hsl(
    h_s: str, h_units: str | None, sat_s: str, light_s: str
) -> tuple[int, int, int]:
    h = float(h_s)

    if h_units in {None, "deg"}:
        h = h % 360 / 360
    elif h_units == "rad":
        h = h % _RADS / _RADS
    else:
        h %= 1

    s = max(0.0, min(1.0, float(sat_s) / 100))
    li = max(0.0, min(1.0, float(light_s) / 100))

    r_f, g_f, b_f = hls_to_rgb(h, li, s)
    return (round(r_f * 255), round(g_f * 255), round(b_f * 255))


_COLORS_BY_NAME: dict[str, tuple[int, int, int]] = {
    "aliceblue": (240, 248, 255),
    "antiquewhite": (250, 235, 215),
    "aqua": (0, 255, 255),
    "aquamarine": (127, 255, 212),
    "azure": (240, 255, 255),
    "beige": (245, 245, 220),
    "bisque": (255, 228, 196),
    "black": (0, 0, 0),
    "blanchedalmond": (255, 235, 205),
    "blue": (0, 0, 255),
    "blueviolet": (138, 43, 226),
    "brown": (165, 42, 42),
    "burlywood": (222, 184, 135),
    "cadetblue": (95, 158, 160),
    "chartreuse": (127, 255, 0),
    "chocolate": (210, 105, 30),
    "coral": (255, 127, 80),
    "cornflowerblue": (100, 149, 237),
    "cornsilk": (255, 248, 220),
    "crimson": (220, 20, 60),
    "cyan": (0, 255, 255),
    "darkblue": (0, 0, 139),
    "darkcyan": (0, 139, 139),
    "darkgoldenrod": (184, 134, 11),
    "darkgray": (169, 169, 169),
    "darkgreen": (0, 100, 0),
    "darkgrey": (169, 169, 169),
    "darkkhaki": (189, 183, 107),
    "darkmagenta": (139, 0, 139),
    "darkolivegreen": (85, 107, 47),
    "darkorange": (255, 140, 0),
    "darkorchid": (153, 50, 204),
    "darkred": (139, 0, 0),
    "darksalmon": (233, 150, 122),
    "darkseagreen": (143, 188, 143),
    "darkslateblue": (72, 61, 139),
    "darkslategray": (47, 79, 79),
    "darkslategrey": (47, 79, 79),
    "darkturquoise": (0, 206, 209),
    "darkviolet": (148, 0, 211),
    "deeppink": (255, 20, 147),
    "deepskyblue": (0, 191, 255),
    "dimgray": (105, 105, 105),
    "dimgrey": (105, 105, 105),
    "dodgerblue": (30, 144, 255),
    "firebrick": (178, 34, 34),
    "floralwhite": (255, 250, 240),
    "forestgreen": (34, 139, 34),
    "fuchsia": (255, 0, 255),
    "gainsboro": (220, 220, 220),
    "ghostwhite": (248, 248, 255),
    "gold": (255, 215, 0),
    "goldenrod": (218, 165, 32),
    "gray": (128, 128, 128),
    "green": (0, 128, 0),
    "greenyellow": (173, 255, 47),
    "grey": (128, 128, 128),
    "honeydew": (240, 255, 240),
    "hotpink": (255, 105, 180),
    "indianred": (205, 92, 92),
    "indigo": (75, 0, 130),
    "ivory": (255, 255, 240),
    "khaki": (240, 230, 140),
    "lavender": (230, 230, 250),
    "lavenderblush": (255, 240, 245),
    "lawngreen": (124, 252, 0),
    "lemonchiffon": (255, 250, 205),
    "lightblue": (173, 216, 230),
    "lightcoral": (240, 128, 128),
    "lightcyan": (224, 255, 255),
    "lightgoldenrodyellow": (250, 250, 210),
    "lightgray": (211, 211, 211),
    "lightgreen": (144, 238, 144),
    "lightgrey": (211, 211, 211),
    "lightpink": (255, 182, 193),
    "lightsalmon": (255, 160, 122),
    "lightseagreen": (32, 178, 170),
    "lightskyblue": (135, 206, 250),
    "lightslategray": (119, 136, 153),
    "lightslategrey": (119, 136, 153),
    "lightsteelblue": (176, 196, 222),
    "lightyellow": (255, 255, 224),
    "lime": (0, 255, 0),
    "limegreen": (50, 205, 50),
    "linen": (250, 240, 230),
    "magenta": (255, 0, 255),
    "maroon": (128, 0, 0),
    "mediumaquamarine": (102, 205, 170),
    "mediumblue": (0, 0, 205),
    "mediumorchid": (186, 85, 211),
    "mediumpurple": (147, 112, 219),
    "mediumseagreen": (60, 179, 113),
    "mediumslateblue": (123, 104, 238),
    "mediumspringgreen": (0, 250, 154),
    "mediumturquoise": (72, 209, 204),
    "mediumvioletred": (199, 21, 133),
    "midnightblue": (25, 25, 112),
    "mintcream": (245, 255, 250),
    "mistyrose": (255, 228, 225),
    "moccasin": (255, 228, 181),
    "navajowhite": (255, 222, 173),
    "navy": (0, 0, 128),
    "oldlace": (253, 245, 230),
    "olive": (128, 128, 0),
    "olivedrab": (107, 142, 35),
    "orange": (255, 165, 0),
    "orangered": (255, 69, 0),
    "orchid": (218, 112, 214),
    "palegoldenrod": (238, 232, 170),
    "palegreen": (152, 251, 152),
    "paleturquoise": (175, 238, 238),
    "palevioletred": (219, 112, 147),
    "papayawhip": (255, 239, 213),
    "peachpuff": (255, 218, 185),
    "peru": (205, 133, 63),
    "pink": (255, 192, 203),
    "plum": (221, 160, 221),
    "powderblue": (176, 224, 230),
    "purple": (128, 0, 128),
    "red": (255, 0, 0),
    "rosybrown": (188, 143, 143),
    "royalblue": (65, 105, 225),
    "saddlebrown": (139, 69, 19),
    "salmon": (250, 128, 114),
    "sandybrown": (244, 164, 96),
    "seagreen": (46, 139, 87),
    "seashell": (255, 245, 238),
    "sienna": (160, 82, 45),
    "silver": (192, 192, 192),
    "skyblue": (135, 206, 235),
    "slateblue": (106, 90, 205),
    "slategray": (112, 128, 144),
    "slategrey": (112, 128, 144),
    "snow": (255, 250, 250),
    "springgreen": (0, 255, 127),
    "steelblue": (70, 130, 180),
    "tan": (210, 180, 140),
    "teal": (0, 128, 128),
    "thistle": (216, 191, 216),
    "tomato": (255, 99, 71),
    "turquoise": (64, 224, 208),
    "violet": (238, 130, 238),
    "wheat": (245, 222, 179),
    "white": (255, 255, 255),
    "whitesmoke": (245, 245, 245),
    "yellow": (255, 255, 0),
    "yellowgreen": (154, 205, 50),
}

type Color = (
    Literal[
        "aliceblue",
        "antiquewhite",
        "aqua",
        "aquamarine",
        "azure",
        "beige",
        "bisque",
        "black",
        "blanchedalmond",
        "blue",
        "blueviolet",
        "brown",
        "burlywood",
        "cadetblue",
        "chartreuse",
        "chocolate",
        "coral",
        "cornflowerblue",
        "cornsilk",
        "crimson",
        "cyan",
        "darkblue",
        "darkcyan",
        "darkgoldenrod",
        "darkgray",
        "darkgreen",
        "darkgrey",
        "darkkhaki",
        "darkmagenta",
        "darkolivegreen",
        "darkorange",
        "darkorchid",
        "darkred",
        "darksalmon",
        "darkseagreen",
        "darkslateblue",
        "darkslategray",
        "darkslategrey",
        "darkturquoise",
        "darkviolet",
        "deeppink",
        "deepskyblue",
        "dimgray",
        "dimgrey",
        "dodgerblue",
        "firebrick",
        "floralwhite",
        "forestgreen",
        "fuchsia",
        "gainsboro",
        "ghostwhite",
        "gold",
        "goldenrod",
        "gray",
        "green",
        "greenyellow",
        "grey",
        "honeydew",
        "hotpink",
        "indianred",
        "indigo",
        "ivory",
        "khaki",
        "lavender",
        "lavenderblush",
        "lawngreen",
        "lemonchiffon",
        "lightblue",
        "lightcoral",
        "lightcyan",
        "lightgoldenrodyellow",
        "lightgray",
        "lightgreen",
        "lightgrey",
        "lightpink",
        "lightsalmon",
        "lightseagreen",
        "lightskyblue",
        "lightslategray",
        "lightslategrey",
        "lightsteelblue",
        "lightyellow",
        "lime",
        "limegreen",
        "linen",
        "magenta",
        "maroon",
        "mediumaquamarine",
        "mediumblue",
        "mediumorchid",
        "mediumpurple",
        "mediumseagreen",
        "mediumslateblue",
        "mediumspringgreen",
        "mediumturquoise",
        "mediumvioletred",
        "midnightblue",
        "mintcream",
        "mistyrose",
        "moccasin",
        "navajowhite",
        "navy",
        "oldlace",
        "olive",
        "olivedrab",
        "orange",
        "orangered",
        "orchid",
        "palegoldenrod",
        "palegreen",
        "paleturquoise",
        "palevioletred",
        "papayawhip",
        "peachpuff",
        "peru",
        "pink",
        "plum",
        "powderblue",
        "purple",
        "red",
        "rosybrown",
        "royalblue",
        "saddlebrown",
        "salmon",
        "sandybrown",
        "seagreen",
        "seashell",
        "sienna",
        "silver",
        "skyblue",
        "slateblue",
        "slategray",
        "slategrey",
        "snow",
        "springgreen",
        "steelblue",
        "tan",
        "teal",
        "thistle",
        "tomato",
        "turquoise",
        "transparent",
        "violet",
        "wheat",
        "white",
        "whitesmoke",
        "yellow",
        "yellowgreen",
    ]
    | str
)
"""A CSS3 color string.

Accepts named colors (``red``, ``blue``), hex (``#rgb``, ``#rrggbb``),
``rgb()``, ``rgba()``, ``hsl()``, ``hsla()``, and ``transparent``.

See the `CSS Color Module Level 3 <http://www.w3.org/TR/css3-color/#svg-color>`_
specification.
"""

type Opacity = float
type StrokeWidth = float
