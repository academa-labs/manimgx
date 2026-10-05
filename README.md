<p align="center">
  <a href="https://manimgx.academa.ai">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://manimgx.academa.ai/showcase/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://manimgx.academa.ai/showcase/logo-light.svg">
      <img alt="ManimGX" src="https://manimgx.academa.ai/showcase/logo-light.svg" width="640">
    </picture>
  </a>
</p>

<p align="center">
  <b>Blazingly fast 3D animation for agents, with <a href="https://www.manim.community">Manim CE's API</a>.</b><br>
  Powered by Rust and wgpu. Install with a prompt or pip. Run in the browser.
</p>

<p align="center">
  <a href="https://coverage.manimgx.academa.ai"><img alt="Test coverage" src="https://img.shields.io/endpoint?url=https%3A%2F%2Fcoverage.manimgx.academa.ai%2Fbadge.json&label=coverage"></a>
  <a href="https://manimgx.academa.ai"><img alt="Documentation built with Zensical" src="https://img.shields.io/badge/docs-Zensical-58c4dd"></a>
  <a href="https://pypi.org/project/manimgx/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/manimgx?color=58c4dd&label=PyPI"></a>
  <a href="https://www.npmjs.com/package/manimgx"><img alt="npm version" src="https://img.shields.io/npm/v/manimgx?color=58c4dd"></a>
  <a href="https://pepy.tech/projects/manimgx"><img alt="PyPI total downloads" src="https://img.shields.io/pepy/dt/manimgx?color=58c4dd&label=PyPI%20downloads"></a>
  <a href="https://www.npmjs.com/package/manimgx"><img alt="npm monthly downloads" src="https://img.shields.io/npm/dm/manimgx?color=58c4dd&label=npm%20downloads"></a>
</p>

<p align="center">
  <a href="https://github.com/academa-labs/manimgx/blob/main/examples/hopf_fibration.py"><picture><source media="(max-resolution: 1.25dppx)" srcset="https://manimgx.academa.ai/showcase/hopf_fibration.avif"><img alt="The Hopf fibration: the circles of the 3-sphere, linked in nested tori, with beads riding them" src="https://manimgx.academa.ai/showcase/hopf_fibration@2x.avif" width="32%"></picture></a>
  <a href="https://github.com/academa-labs/manimgx/blob/main/examples/clifford_torus.py"><picture><source media="(max-resolution: 1.25dppx)" srcset="https://manimgx.academa.ai/showcase/clifford_torus.avif"><img alt="A torus turned inside out by a quarter turn in four dimensions" src="https://manimgx.academa.ai/showcase/clifford_torus@2x.avif" width="32%"></picture></a>
  <a href="https://github.com/academa-labs/manimgx/blob/main/examples/kaleidoscope_sphere.py"><picture><source media="(max-resolution: 1.25dppx)" srcset="https://manimgx.academa.ai/showcase/kaleidoscope_sphere.avif"><img alt="A kaleidoscope on the sphere: tiles turning over, wave after wave, between three mirrors" src="https://manimgx.academa.ai/showcase/kaleidoscope_sphere@2x.avif" width="32%"></picture></a>
  <br>
  <a href="https://github.com/academa-labs/manimgx/blob/main/examples/riemann_surfaces.py"><picture><source media="(max-resolution: 1.25dppx)" srcset="https://manimgx.academa.ai/showcase/riemann_surfaces.avif"><img alt="The Riemann surface of log z: an endless staircase" src="https://manimgx.academa.ai/showcase/riemann_surfaces@2x.avif" width="32%"></picture></a>
  <a href="https://github.com/academa-labs/manimgx/blob/main/examples/turing_torus.py"><picture><source media="(max-resolution: 1.25dppx)" srcset="https://manimgx.academa.ai/showcase/turing_torus.avif"><img alt="Turing patterns growing on a torus" src="https://manimgx.academa.ai/showcase/turing_torus@2x.avif" width="32%"></picture></a>
  <a href="https://github.com/academa-labs/manimgx/blob/main/examples/lozenge_cubes.py"><picture><source media="(max-resolution: 1.25dppx)" srcset="https://manimgx.academa.ai/showcase/lozenge_cubes.avif"><img alt="A pile of cubes: a lozenge tiling of a hexagon, turned in three dimensions" src="https://manimgx.academa.ai/showcase/lozenge_cubes@2x.avif" width="32%"></picture></a>
</p>

**10 seconds of 3D video, rendered in 0.85 seconds.** On our 1080p60 benchmark,
manimgx is **286× faster than Manim CE**, **7.3× faster than ManimGL**, and
**22× faster than Blender Workbench**, from launch to finished MP4.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://manimgx.academa.ai/images/benchmark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://manimgx.academa.ai/images/benchmark-light.svg">
    <img alt="Render times: manimgx 0.85 s, ManimGL 6.2 s, Blender Workbench 18 s, Blender EEVEE 3 min 59 s, Manim CE 4 min 03 s" src="https://manimgx.academa.ai/images/benchmark-light.svg" width="100%">
  </picture>
</p>

<p align="center">
  <i>Apple M4 Pro, each tool's default encoder settings. manimgx favors speed over file size.
  <a href="https://github.com/academa-labs/manimgx/tree/main/scripts/benchmark">Scenes, settings and results</a>.</i>
</p>

## Get started

**With a prompt.** Paste into Claude Code, Codex, or Cursor. Your agent handles setup:

```text
Follow https://manimgx.academa.ai/llms.txt.
Install manimgx, make a 3D animation of the solar system, and open it.
```

**With pip.** Install on macOS, Linux or Windows with Python 3.13+:

```sh
pip install manimgx
```

Fonts, typesetting and video encoding are included.

## From Python to MP4

Save this as `scene.py`:

```python
import manimgx as m


class Hello3D(m.ThreeDScene):
    def construct(self) -> None:
        self.set_camera_orientation(phi=65 * m.DEGREES, theta=-45 * m.DEGREES)
        self.begin_ambient_camera_rotation(rate=0.5)
        cube = m.Cube(side_length=3, fill_opacity=0.3, stroke_width=2)
        self.play(m.Create(cube), run_time=2)
        self.wait(4)
```

Render it:

```sh
manimgx render scene.py
```

You get `Hello3D.mp4`, a 1080p60 video:

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://manimgx.academa.ai/films/readme-Hello3D.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://manimgx.academa.ai/films/readme-Hello3D-light.svg">
    <img alt="A blue cube is drawn as the camera circles it" src="https://manimgx.academa.ai/films/readme-Hello3D-light.svg#readme" width="100%">
  </picture>
</p>

## Why manimgx?

**An API for 3D video in the age of agents.** Your agent writes Python using
[Manim CE's API](https://www.manim.community).
manimgx's Rust + wgpu engine renders the MP4, blazingly fast.

- **Fully statically typed.** Keyword arguments and `.animate` chains included.
- **2D and 3D together.** Surfaces, meshes and moving cameras alongside text, equations
  and plots.
- **Runs in the browser.** `npm install manimgx`. [Pyodide](https://pyodide.org) runs
  Python in a Web Worker; WebGPU renders the scene.
  [Embed a scene](https://manimgx.academa.ai/user-guide/rendering/#in-the-browser) with no render server.
- **Agent feedback.** Storyboards and [2D layout checks](https://manimgx.academa.ai/user-guide/rendering/#check).
- **Text and math.** Write LaTeX or Typst. No LaTeX installation needed.
- **Speech in sync.** [Match animations to spoken words](https://manimgx.academa.ai/user-guide/sound-and-voice/)
  with `self.say()`.

## On the shoulders of giants

[Grant Sanderson](https://www.3blue1brown.com) created
[Manim](https://github.com/3b1b/manim). The [Manim Community](https://www.manim.community)
developed the API that manimgx builds on.

The engine draws with [wgpu](https://wgpu.rs), typesets text and math with
[Typst](https://typst.app) and [mitex](https://github.com/mitex-rs/mitex), encodes video
with [x264](https://www.videolan.org/developers/x264.html), and decodes audio with
[FFmpeg](https://ffmpeg.org) and [libopus](https://opus-codec.org).

[NumPy](https://numpy.org) powers the geometry, [PyO3](https://pyo3.rs) connects Python
and Rust, and [Pyodide](https://pyodide.org) runs Python in the browser.
[Noto](https://notofonts.github.io) supplies fonts, and
[Mesa](https://mesa3d.org)'s lavapipe lets Linux render without a GPU.

## Learn more

- [User Guide](https://manimgx.academa.ai/user-guide/quickstart/)
- [Examples](https://manimgx.academa.ai/gallery/)
- [API Reference](https://manimgx.academa.ai/reference/)
- [Changelog](https://manimgx.academa.ai/changelog/)
- [Citing manimgx](https://github.com/academa-labs/manimgx/blob/main/CITATION.cff)

## Community

Questions, bug reports and feature requests start with an
[issue](https://github.com/academa-labs/manimgx/issues/new/choose).
To contribute, read [Contributing](https://github.com/academa-labs/manimgx/blob/main/.github/CONTRIBUTING.md)
and the [Developer Guide](https://manimgx.academa.ai/developer-guide/).

Everyone participating follows the
[Code of Conduct](https://github.com/academa-labs/manimgx/blob/main/.github/CODE_OF_CONDUCT.md).
Report vulnerabilities privately through the
[security policy](https://github.com/academa-labs/manimgx/blob/main/.github/SECURITY.md).

## License

manimgx's own code is [MIT-licensed](https://github.com/academa-labs/manimgx/blob/main/LICENSE).
Native wheels include x264 and are GPL-3.0-or-later as a whole.

Bundled components retain their licenses: see the
[third-party notices](https://github.com/academa-labs/manimgx/blob/main/LICENSE-THIRD-PARTY),
[Linux renderer notices](https://github.com/academa-labs/manimgx/blob/main/LICENSE-LAVAPIPE),
and the [Noto](https://github.com/academa-labs/manimgx/blob/main/fonts/manimgx-fonts/LICENSE)
and [Noto CJK](https://github.com/academa-labs/manimgx/blob/main/fonts/manimgx-fonts-cjk/LICENSE) font licenses.

This software uses code of [FFmpeg](https://ffmpeg.org) licensed under
[LGPL-2.1-or-later](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html).
Complete source, including FFmpeg, is in `manimgx-X.Y.Z-source.tar.xz` on each
[GitHub release](https://github.com/academa-labs/manimgx/releases).
