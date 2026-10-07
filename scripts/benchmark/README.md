# Benchmarks

Five scenes rendered by ManimGX, ManimGL, ManimCE, Blender Workbench, and Blender EEVEE at 1920 × 1080 and 60 fps. Each engine exports an H.264 MP4 through its native renderer. The scene implementations and rendering adapters are in `scenes/`.

## Scenes

| Scene | Duration | Content |
| --- | ---: | --- |
| `orbit` | 10 s | A 48 × 48 surface, three axes, a progressively drawn curve, a moving sphere, and an orbiting camera. |
| `matrix` | 7.2 s | A matrix-vector product, expanded arithmetic, and the resulting vector. |
| `pendulums` | 13 s | Twelve pendulums with different lengths, animated rods and bobs, and a title. |
| `hierarchy` | 3 s | Five planets and five moons moving around a central sphere, viewed by an orbiting camera. |
| `linked_rings` | 3 s | Eight animated 32 × 8 torus links with an orbiting camera and a shared key-light direction. |

Total video duration: 36.2 seconds. Geometry, animation, text, and shading use each engine's native APIs.

## Results

Measured October 7, 2026, on an Apple M4 Pro with 12 CPU cores and 24 GB memory, running macOS 15.7.9. Engine versions: ManimGX 0.1.0, ManimGL 1.7.2, ManimCE 0.21.0, and Blender 5.2.2 LTS. Times are in seconds.

| Scene | ManimGX | ManimGL | ManimCE | Blender Workbench | Blender EEVEE |
| --- | ---: | ---: | ---: | ---: | ---: |
| Surface and orbiting camera | 1.184 | 6.463 | 211.809 | 16.563 | 220.242 |
| Matrix-vector multiplication | 0.360 | 8.287 | 7.140 | 11.045 | 90.798 |
| Twelve pendulums | 0.756 | 16.812 | 4.745 | 19.860 | 165.890 |
| Planets and moons | 0.334 | 1.789 | 16.169 | 4.979 | 62.265 |
| Linked rings | 0.443 | 1.933 | 38.962 | 5.163 | 62.200 |
| Total | 3.078 | 35.284 | 278.826 | 57.611 | 601.395 |

Values are arithmetic means of three runs per scene for GX and GL, and one run per scene for CE and each Blender renderer. Totals sum the five scene means. `results.json` contains all 45 measurements and their summaries. Lower is better.

## Rendering settings

GX, GL, and CE use x264's `ultrafast` preset with CRF 23. Blender uses `REALTIME`, its fastest available encoding preset, with custom CRF 23. Its encoded options correspond to x264 `superfast`. Video output uses `yuv420p`. EEVEE uses 64 samples; Workbench uses its native rasterizer.

Each run starts a fresh process and uses a separate output and scene-cache directory. Wall time spans process launch through exit, including scene construction, rendering, encoding, and MP4 finalization. Full decoding, presentation-timestamp checks, resolution checks, and encoder-option verification run after the timer stops. GX's additional closing frame is permitted. Runs execute sequentially. Operating-system and GPU-driver caches remain available.

## Run

The runner supports macOS and Linux. Install this repository's environment with `just sync`. Install FFmpeg, including `ffprobe`, a LaTeX distribution for CE and GL, and Blender 5.2.2 LTS. GL requires an available OpenGL context.

Create separate CE and GL environments from the repository root:

```sh
uv venv --python 3.13 .cache/benchmark-envs/ce
uv pip install --python .cache/benchmark-envs/ce/bin/python 'manim==0.21.0'
uv venv --python 3.12 .cache/benchmark-envs/gl
uv pip install --python .cache/benchmark-envs/gl/bin/python 'manimgl==1.7.2' 'setuptools==80.9.0'
```

Run all five scenes and engines, supplying the Blender executable path:

```sh
uv run --frozen python -m scripts.benchmark.run \
  --out .cache/comparison/five-scenes \
  --ce-python .cache/benchmark-envs/ce/bin/python \
  --manimgl .cache/benchmark-envs/gl/bin/manimgl \
  --blender /path/to/blender
```

The output directory must not already exist. It receives every MP4, process log, command, validation result, and individual timing, with `results.json` checkpointed after each run. A failed, invalid, or timed-out run stops the command and remains recorded. A total is available only after all required runs for an engine complete.

`--scenes orbit linked_rings` limits the scenes. `--tools manimgx manimgl` limits the engines. `--rounds 1` sets the number of runs for every engine. `--timeout 900` sets the timeout in seconds per render. `--dry-run` writes the command plan without starting renderers.

## Chart

Generate the dark and light SVG charts from the recorded results:

```sh
uv run --frozen python scripts/benchmark/chart.py
```

The chart divides every engine's total by GX's total, so GX equals one second. To chart a new complete run into a separate directory:

```sh
uv run --frozen python scripts/benchmark/chart.py \
  --results .cache/comparison/five-scenes/results.json \
  --out .cache/comparison/five-scenes/charts
```

## Quality images

Render the linked-rings frame at 2.5 seconds:

```sh
uv run --frozen python -m scripts.benchmark.quality \
  --out .cache/comparison/linked-rings-images \
  --ce-python .cache/benchmark-envs/ce/bin/python \
  --gl-python .cache/benchmark-envs/gl/bin/python \
  --blender /path/to/blender
```

`native/` contains each renderer's transparent 1920 × 1080 PNG and process log. `images/` contains the ten website PNGs: five with `#0B0C0F` backgrounds and five with `#FFFFFF` backgrounds, matching the website's dark and light themes. Both backgrounds use the same native frame. The still-image script supplies CE and GL material colors separately; each engine retains its native shading. The website displays the same viewport of every frame.
