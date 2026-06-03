"""CE's frames against manimgx's, at the same scene times.

Each manimgx frame (frame k shows the scene at k/fps, exactly) is compared with the frame CE has
on screen at that scene time: CE's latest frame at or before it, since a frame stays up until
the next one. Never by index: CE rounds each play to whole frames (after a 0.75 s play at 10 fps
its frames fall at .75, .85, … while manimgx's stay at .8, .9, …), floors frozen waits, and
never shows a scene's last animation landing, and none of that may count against manimgx.
From the end of CE's scene on, only a CE frame of exactly the same time is compared — the
landed scene, which CE shows only when its float arithmetic gives a play one frame too many —
so manimgx's closing frame is otherwise its own. A CE frame on screen at no manimgx frame's
time (up for less than a frame, or after manimgx's scene ended) is unpaired.

Each pair is measured in every metric (all 0–255), so the metric and tolerance a reviewer picks
(`settings.json`) apply without measuring again:

- `local_max`: the largest mean, over any 7×7 window, of each pixel's largest channel
  difference. A lone wrong pixel fades to 1/49 of itself; a wrong stroke or shape survives —
  edge noise between two rasterizers stays low.
- `mae`: the mean channel difference over the frame.
- `rmse`: its root mean square.
- `max`: the largest channel difference anywhere.

The verdict this feeds only sorts cases for review: CE has bugs of its own, "same" is not
"correct", and a person's review overrides it either way.
"""

from collections.abc import Generator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
from tests.integration.corpus.case import METRICS, Comparison, Frames
from tests.integration.corpus.frames import Pixels, decode

WINDOW = 7


def measure(a: Pixels, b: Pixels) -> tuple[float, ...]:
    """The pair's difference in each metric, in the order of `METRICS`."""
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    per_pixel = d.max(axis=2).astype(np.float64)
    k = WINDOW
    s = np.zeros((per_pixel.shape[0] + 1, per_pixel.shape[1] + 1))
    s[1:, 1:] = per_pixel.cumsum(axis=0).cumsum(axis=1)
    windows = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
    squared = np.square(d, dtype=np.float64)
    found = {
        "local_max": float(windows.max() / (k * k)),
        "mae": float(d.mean()),
        "rmse": float(np.sqrt(squared.mean())),
        "max": float(d.max()),
    }
    return tuple(found[metric] for metric in METRICS)


def pair(
    ce: Frames, manimgx: Frames, fps: int
) -> tuple[list[tuple[int, int]], list[int]]:
    """(the CE frame on screen at a manimgx frame's scene time, that manimgx frame); and the
    CE frames on screen at none."""
    times = ce.times(fps)  # in order: plays follow one another
    pairs: list[tuple[int, int]] = []
    shown = -1  # the CE frame on screen
    for k in range(manimgx.count):
        time = Fraction(k, fps)
        while shown + 1 < len(times) and times[shown + 1] <= time:
            shown += 1
        if shown < 0 or (time >= ce.duration and times[shown] != time):
            continue  # nothing yet, or CE's scene is over and it never showed this moment
        pairs.append((shown, k))
    used = {i for i, _ in pairs}
    return pairs, [i for i in range(len(times)) if i not in used]


def compare(
    ce: Frames,
    manimgx: Frames,
    ce_video: Path,
    manimgx_video: Path,
    size: tuple[int, int],
    fps: int,
) -> Comparison:
    pairs, unpaired = pair(ce, manimgx, fps)
    ce_hashes, mx_hashes = ce.hashes(), manimgx.hashes()
    known: dict[tuple[str, str], tuple[float, ...]] = {}  # held frames repeat pairs
    rows: list[tuple[int, int, tuple[float, ...]]] = []
    ce_frames = _Cursor(decode(ce_video, size))
    mx_frames = _Cursor(decode(manimgx_video, size))
    try:
        for i, k in pairs:  # both indices only grow: each video is read once
            key = (ce_hashes[i], mx_hashes[k])
            if key not in known:
                known[key] = measure(ce_frames.at(i), mx_frames.at(k))
            rows.append((i, k, known[key]))
    finally:
        ce_frames.close()
        mx_frames.close()
    return Comparison(pairs=tuple(rows), unpaired=tuple(unpaired))


@dataclass(frozen=True, slots=True)
class Slot:
    """A step of the timeline: a scene time, and the frame each engine has on screen then
    (`ce_time`: the scene time CE's frame shows, which may be up to a frame earlier)."""

    time: Fraction
    ce: int | None
    ce_time: Fraction | None
    manimgx: int | None


def slots(ce: Frames | None, manimgx: Frames | None, fps: int) -> list[Slot]:
    """The timeline: a slot per manimgx frame, with the CE frame on screen at its time, then
    CE's frames that no manimgx frame is compared with, where their time falls."""
    ce_times = [] if ce is None else ce.times(fps)
    if manimgx is None:
        return [Slot(t, i, t, None) for i, t in enumerate(ce_times)]
    pairs, unpaired = ([], []) if ce is None else pair(ce, manimgx, fps)
    partner = {k: i for i, k in pairs}
    found = [
        Slot(
            Fraction(k, fps),
            partner.get(k),
            None if k not in partner else ce_times[partner[k]],
            k,
        )
        for k in range(manimgx.count)
    ]
    found += [Slot(ce_times[i], i, ce_times[i], None) for i in unpaired]
    return sorted(found, key=lambda s: (s.time, s.manimgx is None))


class _Cursor:
    """Random access, forward only, into a stream of frames."""

    def __init__(self, frames: Generator[Pixels]) -> None:
        self._frames = frames
        self._index = -1
        self._frame: Pixels | None = None

    def at(self, index: int) -> Pixels:
        if index < self._index:
            msg = f"frame {index} is behind the stream (at {self._index})"
            raise ValueError(msg)
        while self._index < index:
            self._frame = next(self._frames)
            self._index += 1
        assert self._frame is not None
        return self._frame

    def close(self) -> None:
        self._frames.close()
