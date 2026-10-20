---
hide:
  - navigation
---

# Changelog

The notable changes to ManimGX, release by release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and ManimGX follows
[Semantic Versioning](https://semver.org/).

<!--
### Added
### Changed
### Fixed
### Removed
-->

## Unreleased

### Added

- Add a preview image and social metadata when sharing website and documentation links.
- Credit Academa and the creators in the README.
- Tell a page how a scene fares in `<manimgx-player>`, as a media element does: a `loadeddata` event when a run of the scene has made its first frame, and an `error` event when a run fails, with the error's `message`, `type`, `line` and `trace` in `player.error` until a later run makes its first frame.
- Tell a page when `<manimgx-player>` cannot play at all: a `failure` event, with why in `player.failure` (the browser has no WebGPU, no GPU WebGPU can draw with, or a GPU without float32 blending or float32 depth with stencil; or Python, ManimGX or the engine failed). `unsupported()` finds out what the browser lacks before a page makes a player.

### Changed

- Render faster: a graph's area reads its points' coordinates all at once, colors mix without numpy's overhead and are converted to OKLab once, and a family is listed in one pass. The frames are the same.
- Draw and encode a film's frames on a thread of their own: the scene's Python no longer waits for the GPU or the encoder, but for the pixels it asks for and its video's end. The videos are the same.
- Hold the API to its declared types, which ty checks where it is called: `add`, `ApplyFunction`, `SurroundingRectangle`, `ArcPolygonFromArcs` and `voices.Fal` no longer check them again as they run, and an `Animation` always has a mobject (`Wait` and a sound pass a plain `Mobject()`, where `None` stood). `interpolate` is typed by what it mixes (numbers, complex numbers or arrays), and `midpoint`, `center_of_mass`, `bezier`, `partial_bezier_points`, `subdivide_bezier` and `bezier_remap` by the array-likes they take (and `subdivide_bezier`'s count by numpy's integers too).
- Show measured render times in a static benchmark chart.
- Use a Markdown table for the benchmark comparison images.
- Install ManimGX in the Quickstart with one command, `pip install manimgx`, and run `manimgx` directly throughout the docs.
- Move the benchmark to `benchmarks/`, whose README explains its scenes, method and results; the README's numbers link to it.
- Arrange the Rendering and sharing page by command, with settings, tall videos and rendering from Python under Render.
- Check the browser's GPU before downloading Python: a browser that cannot draw a film no longer downloads Pyodide and ManimGX to find out. A player made after one failed begins again, so a page can retry a download that failed.

### Fixed

- Keep resources needed by queued video frames until their transparency retries finish, fixing render failures during cache cleanup ([#16](https://github.com/academa-labs/manimgx/issues/16)).
- Draw a storyboard picture without dropping the frame the film holds back, fixing `manimgx render` failures ("unknown shape") under memory pressure.
- Draw a vectorized curve whose function gives a component as one number (`use_vectorized` with `lambda t: (t, t**2, 0)`), which failed with numpy's inhomogeneous-shape error.
- Name a partite layout's vertex that is not in the graph, and a vertex's keywords or an edge's `tip_config` that are not a mapping, in the error raised.
- Preserve the benchmark comparison images' aspect ratios when PyPI narrows the README table.
- Credit Filament, whose code the 3D lighting is adapted from, in the README and the wheels' third-party notices.
- Keep webpack from compiling the player's import of its engine into "Cannot find module": the bundle tells bundlers to leave that import alone.

## 0.1.1

### Changed

- Updated package author metadata to Academa Team. The font packages have metadata-only post-releases; their font files are unchanged.

### Fixed

- Fixed GPU validation failures when meshes with materials share a scene with ordinary meshes, overlays, or point sprites, including during fades.

## 0.1.0

First release of ManimGX.
