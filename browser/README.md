# manimgx

[manimgx](https://manimgx.academa.ai/) in the browser: a scene written in Python, with Manim
Community Edition's API, made and played in the page by manimgx's own player, drawn with
WebGPU.

```sh
npm install manimgx
```

```html
<script type="module">
  import "manimgx";
</script>

<manimgx-player autoplay>
  <script type="text/python">
    import manimgx as m

    class Euler(m.Scene):
        def construct(self):
            circle = m.Circle(color=m.BLUE, fill_opacity=0.5)
            self.play(m.Create(circle), m.Write(m.MathTex(r"e^{i\pi} + 1 = 0").next_to(circle, m.DOWN)))
  </script>
</manimgx-player>
```

Or from JavaScript:

```js
import "manimgx";

const player = document.createElement("manimgx-player");
player.source = code; // a Python module; set it again, and the film is made again, the time kept
document.body.append(player);
```

- **Python, in the page.** [Pyodide](https://pyodide.org) runs the scene in a Web Worker, with
  manimgx installed from PyPI (the same version as this package). Nothing runs on a server.
- **manimgx's own player**, the one `manimgx preview` plays a file in: the engine compiled to
  WebAssembly draws the film with WebGPU, and its face over it: the controls, the time, the
  timeline in the scene's plays (each named by its line of code), captions, the scene's error
  and the keys (`?` lists them), all in manimgx's fonts. A click, a tap and a key do the same.
- **Any frame, at once**: the film is recorded as it is made (a *take*: each shape once, then
  each frame), and any moment of it is drawn at once, so it plays before the scene has
  finished and seeks instantly. Each frame is drawn at the size the page shows it, in the
  screen's own pixels: sharp at any size, full screen too.
- **For scripts**: `play()`, `pause()`, `paused`, `currentTime`, `duration`, and `scene`.

The first film downloads Python (Pyodide, about 6 MB) and manimgx (about 20 MB); the browser
keeps both. It needs WebGPU: Chrome and Edge 113+, Safari 26, Firefox 141+ on Windows (not yet
with the float32 blending manimgx's renderer uses).

One file, no dependencies, any bundler. On the command line, `manimgx preview scene.py` plays a
scene file in a window of its own: the same player.
