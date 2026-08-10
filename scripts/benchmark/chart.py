"""The README's chart: the benchmark's 3D scene as a race of bars, a light SVG and a dark one.

    uv run --frozen python scripts/benchmark/chart.py

Reads `results.json` (`run.py` writes it) and writes `docs/content/images/benchmark-light.svg`
and `benchmark-dark.svg`, which the README shows from the docs site, each where its color
scheme is. Each bar grows as its tool renders: in real time until manimgx is done and a
moment more, then fast-forwarded (the chart says by how much) until the slowest is done;
the chart then holds, and starts again. Without motion (`prefers-reduced-motion`), it is
the finished chart.
"""

import json
import math
from pathlib import Path

HERE = Path(__file__).parent
IMAGES = HERE.parents[1] / "docs" / "content" / "images"
SCENE = "orbit"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
THEMES = {
    "light": {
        "text": "#1f2328",
        "muted": "#59636e",
        "grid": "#d1d9e0",
        "bar": "#b8c0ca",
    },
    "dark": {
        "text": "#f0f6fc",
        "muted": "#9198a1",
        "grid": "#3d444d",
        "bar": "#4d5561",
    },
}
WIDTH, LEFT, RIGHT, TOP, ROW, BAR = 880, 180, 92, 44, 44, 22
LIVE, FORWARD, HOLD, RESET = (
    1.2,
    3.5,
    8.0,
    0.4,
)  # s: real time after the fastest, … ends
SPEEDS = (2, 5, 10, 20, 50, 100, 200, 500)  # the fast-forward factors the chart names


class Race:
    """The race's clock: real time until the fastest is done and `LIVE` seconds more, then
    faster and faster (exponentially), so that the slowest is done `FORWARD` seconds
    later; then the finished chart holds for `HOLD` seconds, and `RESET` shrinks it away.
    """

    def __init__(self, fastest: float, slowest: float) -> None:
        self.live = fastest + LIVE
        self.growth = math.log(max(slowest / self.live, 1.0001)) / FORWARD
        self.end = self.live + FORWARD
        self.period = self.end + HOLD + RESET

    def seconds(self, t: float) -> float:
        """The time the tools have rendered for, at t seconds of the race."""
        if t <= self.live:
            return t
        return self.live * math.exp(self.growth * (min(t, self.end) - self.live))

    def at(self, seconds: float) -> float:
        """When the race reaches a time rendered for (the inverse of `seconds`)."""
        if seconds <= self.live:
            return seconds
        return self.live + math.log(seconds / self.live) / self.growth


def duration(seconds: float) -> str:
    """A time as the chart labels it: 0.85s, 6.2s, 27s, 4m 17s."""
    if seconds < 1:
        return f"{seconds:.2f}s"
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 100:
        return f"{seconds:.0f}s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes}m {rest:02d}s"


def chart(rows: list[tuple[str, float]], theme: dict[str, str]) -> str:
    """The bars, fastest first, on a scale of whole minutes, racing."""
    slowest = max(seconds for _, seconds in rows)
    race = Race(min(seconds for _, seconds in rows), slowest)
    minutes = int(slowest // 60) + 1
    span = WIDTH - LEFT - RIGHT

    def x(seconds: float) -> float:
        """Where a time is on the chart."""
        return LEFT + span * seconds / (60 * minutes)

    def percent(t: float) -> str:
        return f"{100 * t / race.period:.3f}%"

    reset = race.period - RESET
    height = TOP + ROW * len(rows) + 34
    styles = [
        (
            ".bar{transform-box:fill-box;transform-origin:0 50%;"
            f"animation:{race.period:.3f}s linear infinite}}"
        ),
        f".done{{animation:{race.period:.3f}s step-end infinite}}",
        (
            "@media (prefers-reduced-motion:reduce){.bar,.done,.clock{animation:none}"
            ".clock{opacity:0}}"
        ),
    ]
    parts = []
    bottom = TOP + ROW * len(rows)
    for minute in range(minutes + 1):
        at = x(60 * minute)
        parts.append(
            f'<line x1="{at:.1f}" y1="{TOP - 6}" x2="{at:.1f}" y2="{bottom}"'
            f' stroke="{theme["grid"]}" stroke-width="1"/>'
        )
        label = "0s" if minute == 0 else f"{minute}min"
        parts.append(
            f'<text x="{at:.1f}" y="{bottom + 22}" fill="{theme["muted"]}"'
            f' font-size="13" text-anchor="middle">{label}</text>'
        )
    for i, (name, seconds) in enumerate(rows):
        y = TOP + ROW * i + (ROW - BAR) / 2
        ours = name == "manimgx"
        weight = ' font-weight="700"' if ours else ""
        fill = "url(#manimgx)" if ours else theme["bar"]
        width = max(x(seconds) - LEFT, 3)
        done = race.at(seconds)
        # the bar's length through the race: sampled every 0.05 s until it is done
        stops = [0.0, *(k * 0.05 for k in range(1, int(done / 0.05) + 1)), done]
        frames = ["0%{transform:scaleX(0)}"]
        frames += [
            f"{percent(t)}{{transform:scaleX({race.seconds(t) / seconds:.4f})}}"
            for t in stops[1:]
        ]
        frames += [
            f"{percent(reset)}{{transform:scaleX(1)}}",
            "100%{transform:scaleX(0)}",
        ]
        styles.append(f"@keyframes b{i}{{{''.join(frames)}}}")
        styles.append(f"#b{i}{{animation-name:b{i}}}")
        styles.append(
            f"@keyframes t{i}{{0%{{opacity:0}}{percent(done)}{{opacity:1}}"
            f"{percent(reset)}{{opacity:0}}}}#t{i}{{animation-name:t{i}}}"
        )
        parts.append(
            f'<text x="{LEFT - 16}" y="{y + BAR / 2 + 5:.1f}" fill="{theme["text"]}"'
            f' text-anchor="end"{weight}>{name}</text>'
        )
        parts.append(
            f'<rect id="b{i}" class="bar" x="{LEFT}" y="{y:.1f}" width="{width:.1f}"'
            f' height="{BAR}" rx="4" fill="{fill}"/>'
        )
        parts.append(
            f'<text id="t{i}" class="done" x="{LEFT + width + 10:.1f}"'
            f' y="{y + BAR / 2 + 5:.1f}"'
            f' fill="{theme["text"] if ours else theme["muted"]}"{weight}>'
            f"{duration(seconds)}</text>"
        )
    # the clock: in real time, then fast-forwarded, by how much
    captions = [("real time", 0.0)]
    for factor in SPEEDS:
        t = race.live + math.log(factor / (race.growth * race.live)) / race.growth
        if race.live < t < race.end:
            captions.append((f"fast-forward ×{factor}", t))
    captions.append(("", race.end))
    for k, (text, start) in enumerate(captions[:-1]):
        stop = captions[k + 1][1]
        styles.append(
            f"@keyframes c{k}{{0%{{opacity:0}}{percent(start)}{{opacity:1}}"
            f"{percent(stop)}{{opacity:0}}}}"
            f"#c{k}{{animation:c{k} {race.period:.3f}s step-end infinite}}"
        )
        parts.append(
            f'<text id="c{k}" class="clock" x="{WIDTH - 12}" y="18" opacity="0"'
            f' fill="{theme["muted"]}" font-size="13" text-anchor="end">{text}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}"'
        f' viewBox="0 0 {WIDTH} {height}" font-family="{FONT}" font-size="15">'
        f"<style>{''.join(styles)}</style>"
        '<defs><linearGradient id="manimgx" x1="0" x2="1">'
        '<stop offset="0" stop-color="#58c4dd"/><stop offset="0.5"'
        ' stop-color="#5cd0b3"/>'
        '<stop offset="1" stop-color="#f7d96f"/></linearGradient></defs>'
        + "".join(parts)
        + "</svg>\n"
    )


def main() -> None:
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    rows = sorted(
        ((row["label"], row["median"]) for row in results["scenes"][SCENE].values()),
        key=lambda row: row[1],
    )
    for name, theme in THEMES.items():
        path = IMAGES / f"benchmark-{name}.svg"
        path.write_text(chart(rows, theme), encoding="utf-8")
        print(f"{path}: {path.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
