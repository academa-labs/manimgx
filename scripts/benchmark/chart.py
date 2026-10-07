"""The README's chart: the five-scene suite as a race of bars, light and dark.

    uv run --frozen python scripts/benchmark/chart.py

Reads `results.json` and writes `docs/content/images/benchmark-light.svg`
and `benchmark-dark.svg`, which the README shows from the docs site, each where its color
scheme is. Times are divided by manimgx's suite total, so its bar finishes at one second.
Each bar grows on this normalized clock until manimgx is done and a
moment more, then fast-forwarded (the chart says by how much) until the slowest is done;
the chart then holds, and starts again. Without motion (`prefers-reduced-motion`), it is
the finished chart.
"""

import argparse
import json
import math
from pathlib import Path

HERE = Path(__file__).parent
IMAGES = HERE.parents[1] / "docs" / "content" / "images"
LABELS = {
    "manimgx": "ManimGX",
    "manim_ce": "ManimCE",
    "manimgl": "ManimGL",
    "blender_workbench": "Blender (Workbench)",
    "blender_eevee": "Blender (EEVEE)",
}
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
    """Normalized seconds, without unnecessary trailing zeros."""
    return f"{seconds:.2f}".rstrip("0").rstrip(".") + "s"


def normalized_rows(totals: dict[str, float]) -> list[tuple[str, float]]:
    """Keep every engine's relative time while setting manimgx to one second."""
    return sorted(
        (
            (LABELS[tool], seconds / totals["manimgx"])
            for tool, seconds in totals.items()
        ),
        key=lambda row: row[1],
    )


def chart(rows: list[tuple[str, float]], theme: dict[str, str]) -> str:
    """The bars, fastest first, on a normalized seconds scale, racing."""
    slowest = max(seconds for _, seconds in rows)
    race = Race(min(seconds for _, seconds in rows), slowest)
    magnitude = 10 ** math.floor(math.log10(slowest / 6))
    step = next(
        factor * magnitude
        for factor in (1, 2, 5, 10)
        if factor * magnitude >= slowest / 6
    )
    ticks = math.ceil(slowest / step)
    limit = ticks * step
    span = WIDTH - LEFT - RIGHT

    def x(seconds: float) -> float:
        """Where a time is on the chart."""
        return LEFT + span * seconds / limit

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
    parts = [
        f'<text x="{LEFT}" y="18" fill="{theme["muted"]}" font-size="13">'
        "Normalized: ManimGX = 1s</text>"
    ]
    bottom = TOP + ROW * len(rows)
    for tick in range(ticks + 1):
        at = x(tick * step)
        parts.append(
            f'<line x1="{at:.1f}" y1="{TOP - 6}" x2="{at:.1f}" y2="{bottom}"'
            f' stroke="{theme["grid"]}" stroke-width="1"/>'
        )
        label = duration(tick * step)
        parts.append(
            f'<text x="{at:.1f}" y="{bottom + 22}" fill="{theme["muted"]}"'
            f' font-size="13" text-anchor="middle">{label}</text>'
        )
    for i, (name, seconds) in enumerate(rows):
        y = TOP + ROW * i + (ROW - BAR) / 2
        ours = name == LABELS["manimgx"]
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
    # The normalized clock, then fast-forwarded, by how much.
    captions = [("", 0.0)]
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
    parser = argparse.ArgumentParser(description="Draw normalized render-time charts.")
    parser.add_argument("--results", type=Path, default=HERE / "results.json")
    parser.add_argument("--out", type=Path, default=IMAGES)
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    if not results.get("complete") or set(results["totals"]) != set(LABELS):
        parser.error("The chart requires complete results for all five engines")
    if set(results["settings"]["scenes"]) != {
        "orbit",
        "matrix",
        "pendulums",
        "hierarchy",
        "linked_rings",
    }:
        parser.error("The chart requires all five scenes")
    args.out.mkdir(parents=True, exist_ok=True)
    rows = normalized_rows(results["totals"])
    for name, theme in THEMES.items():
        path = args.out / f"benchmark-{name}.svg"
        path.write_text(chart(rows, theme), encoding="utf-8")
        print(f"{path}: {path.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
