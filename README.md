<p align="center">
  <a href="https://manimgx.academa.ai">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://manimgx.academa.ai/showcase/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://manimgx.academa.ai/showcase/logo-light.svg">
      <img alt="ManimGX: the word, beside Manim's circle, square and triangle made a sphere, a cube and a pyramid" src="https://manimgx.academa.ai/showcase/logo-light.svg" width="640">
    </picture>
  </a>
</p>

<p align="center">
  <b>The animation engine for agents: blazingly fast math and 3D videos with Manim's Python API, on a Rust GPU core.</b>
</p>

The badges i want are, in this order:

Coverage badge (see rendercv for example), docs badge, says zeniscal, pypi badge, npm badge, pypi total downloads badge, npm total downloads badge

i dont care about the badges below, just do was i say:
<p align="center">
  <a href="https://pypi.org/project/manimgx/"><img alt="PyPI" src="https://img.shields.io/pypi/v/manimgx?color=58c4dd&label=pypi"></a>
  <a href="https://pypi.org/project/manimgx/"><img alt="Python 3.13 and 3.14" src="https://img.shields.io/pypi/pyversions/manimgx?color=58c4dd"></a>
  <a href="https://github.com/academa-labs/manimgx/blob/main/LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-58c4dd"></a>
  <a href="https://manimgx.academa.ai"><img alt="Documentation" src="https://img.shields.io/badge/docs-manimgx.academa.ai-58c4dd"></a>
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

You write Python:

..... very few lines examples


you call manimgx:

.... terminal comand

you get the mp4:

mp4 example


- But blazingly fast (Rust core + wgpu implementaiton) .......

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://manimgx.academa.ai/images/benchmark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://manimgx.academa.ai/images/benchmark-light.svg">
    <img alt="A bar chart of render times: manimgx 0.85 s, ManimGL 6.2 s, Blender 18 s with Workbench and 3 min 59 s with EEVEE, Manim CE 4 min 03 s" src="https://manimgx.academa.ai/images/benchmark-light.svg" width="100%">
  </picture>
</p>

<p align="center">
  <i>A 10-second 3D scene rendered to a 1080p60 MP4 on an M4 Pro, from launch to finished file.
  <a href="https://github.com/academa-labs/manimgx/tree/main/scripts/benchmark">How it was measured</a>.</i>
</p>

- Light-weight: X MB, no system dpendencies
- cross-paltofrm on window,s linux,mac, web, just 1 pip installlawya
- Avaialbe as npm package, runs in a webworker through pyodie. 
- Made for agents: they jsut write python to express all sorts of 3d compteur gprahics videos, with voicevers, get the mp4 fast and get deedbacks.
- Compeltly type safe, mdoern python standard and modern tyevariable usage.
- Manims language manims api, 1:1 compatiblity with manim comunity edition
- Math type setting..

math example... gif

## Highlights

- ⚡️ **Blazingly fast.** On a 3D scene, 280× faster than Manim CE, 7× faster than ManimGL
  and 22× faster than Blender: some 700 frames of 1080p video a second, from launch to MP4.
  A Rust engine draws every frame on the GPU and encodes it as the scene runs.
- 🤖 **Made for agents.** One file in, one MP4 out. `manimgx check` reports what a viewer
  would see wrong, as text an agent can act on, and
  [`llms.txt`](https://manimgx.academa.ai/llms.txt) teaches the API in one read.
- 📦 **One `pip install`, everywhere.** macOS, Linux and Windows. Typst typesets text and
  LaTeX math inside the engine, and x264 encodes inside it too: no LaTeX, no FFmpeg, no
  Cairo.
- 🧮 **Manim's language.** Scenes, mobjects and animations under Manim Community Edition's
  names: what you, and your agent, already know carries over.
- 🧊 **2D and 3D, together.** Surfaces, meshes, point clouds and moving cameras, with text,
  math and graphs in the same frame; 1920 × 1080 by default, 1080 × 1920 for Shorts, Reels
  and TikTok with `-r 1080x1920`.
- ⏱️ **Exact, and typed.** Frame *k* shows the scene at exactly *k*/fps, at every frame rate,
  and every keyword is typed: your editor, or your agent's type checker, catches a
  misspelling before you render.

## Get started

Paste this into Claude Code, Codex, Cursor or any agent that can run commands on your
computer:

```text
Follow https://manimgx.academa.ai/llms.txt to make me a 3D animation of the Hopf fibration, and open it.
```

Or write the scene yourself, and render it (Python 3.13 or 3.14, or
`uv tool install --python 3.14 manimgx`):

```sh
pip install manimgx
manimgx render hopf.py
```

```python
import numpy as np

import manimgx as m


def fiber(theta: float, phi: float, color: str) -> m.ParametricFunction:
    """The circle of the 3-sphere over the point (θ, φ) of the 2-sphere, projected."""

    def point(t: float) -> np.ndarray:
        z1 = np.cos(theta / 2) * np.exp(1j * t)
        z2 = np.sin(theta / 2) * np.exp(1j * (t - phi))
        return np.array([z1.real, z1.imag, z2.real]) / (1 - z2.imag)

    return m.ParametricFunction(point, t_range=[0, m.TAU], color=color, stroke_width=3)


class Hopf(m.ThreeDScene):
    def construct(self) -> None:
        tori = {30: "#ffc94a", 60: "#ff8a3d", 90: "#f0506e", 120: "#6f8cff"}
        fibers = m.VGroup(
            *(
                fiber(theta * m.DEGREES, phi, color)
                for theta, color in tori.items()
                for phi in np.linspace(0, m.TAU, 16, endpoint=False)
            )
        )
        title = m.MathTex(r"S^1 \hookrightarrow S^3 \to S^2").to_corner(m.UL)
        self.add_fixed_in_frame_mobjects(title)
        self.set_camera_orientation(phi=65 * m.DEGREES, theta=30 * m.DEGREES, zoom=1.2)
        self.begin_ambient_camera_rotation(rate=0.2)
        self.play(
            m.LaggedStart(*map(m.Create, fibers), lag_ratio=0.1),
            m.Write(title),
            run_time=6,
        )
        self.wait(4)
```

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://manimgx.academa.ai/films/readme-Hopf.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://manimgx.academa.ai/films/readme-Hopf-light.svg">
    <img alt="The Hopf fibration: 64 circles drawn one after another in four nested tori, gold, orange, rose and blue, as the camera circles them" src="https://manimgx.academa.ai/films/readme-Hopf-light.svg#readme" width="100%">
  </picture>
</p>

Ten seconds of 1080p60 video, rendered in two. The [examples](https://github.com/academa-labs/manimgx/tree/main/examples)
go further: thirty films of real mathematics and physics, each one Python file.

## On the shoulders of giants

Grant Sanderson wrote [manim](https://github.com/3b1b/manim) to make
[3Blue1Brown](https://www.3blue1brown.com)'s videos, and taught a generation to watch
mathematics move. The [Manim Community](https://www.manim.community) made it everyone's.
manimgx speaks their language, and rebuilds everything beneath it: a Rust engine on the GPU,
with Typst and x264 inside, for a time when agents write the scenes.

## Learn more

- [Quickstart](https://manimgx.academa.ai/user-guide/quickstart/): from nothing to a video.
- [User Guide](https://manimgx.academa.ai/user-guide/the-basics/): how a scene is
  made, chapter by chapter.
- [Coming from Manim CE](https://manimgx.academa.ai/user-guide/coming-from-manim-ce/): what
  carries over, and what differs.
- [Reference](https://manimgx.academa.ai/reference/): every mobject, animation and scene, and
  the command line.
- [Changelog](https://manimgx.academa.ai/changelog/)

## Contributing

Bug reports, questions and pull requests are welcome: see the
[contributing guide](https://github.com/academa-labs/manimgx/blob/main/.github/CONTRIBUTING.md)
and the [Developer Guide](https://manimgx.academa.ai/developer-guide/).

## License

manimgx's code is [MIT-licensed](https://github.com/academa-labs/manimgx/blob/main/LICENSE).
Its wheels hold others' code too, under their licenses, which each wheel's
`LICENSE-THIRD-PARTY` lists: FFmpeg's audio decoders among them, under the LGPL-2.1-or-later,
and, in every wheel but the browser's, x264, under the GPL-2.0-or-later, which makes such a
wheel, as a whole, GPL-3.0-or-later. The complete source of a release's wheels, which builds
them offline, is
`manimgx-X.Y.Z-source.tar.xz` on its
[GitHub release](https://github.com/academa-labs/manimgx/releases). This software uses code of
[FFmpeg](https://ffmpeg.org) licensed under the LGPLv2.1 and its source can be downloaded
[here](https://github.com/academa-labs/manimgx/releases).
