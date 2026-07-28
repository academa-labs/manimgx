# Setup

This guide is for working on manimgx itself: its Python package, its Rust engine, its
TypeScript browser package, its tests and these docs. It explains how the project works and
how to work on it. How to propose a
change (issues, pull requests, the use of AI) is in the
[contributing guide](https://github.com/academa-labs/manimgx/blob/main/.github/CONTRIBUTING.md).

This page takes a machine to a clone of manimgx that builds, checks, tests and serves the
docs.

## Prerequisites

manimgx is a Python package with an engine written in Rust. You need four tools; building
and testing it needs nothing else from your system: the engine builds x264 (with NASM, the
assembler x264's x86-64 code is written for), FFmpeg's audio decoders and libopus from their
sources, which its build fetches the first time (with `curl` and `tar`, which macOS, Linux and
Windows have), and the tests read and write video with PyAV, which brings FFmpeg's libraries in
its wheels.

- **[`uv`](https://docs.astral.sh/uv/getting-started/installation/)**: the project
  manager. It installs Python (3.13 or 3.14), every dependency, and manimgx itself,
  compiling its engine.
- **[`just`](https://just.systems/man/en/packages.html)**: the command runner. The
  development tasks are recipes in the
  [`justfile`](https://github.com/academa-labs/manimgx/blob/main/justfile).
- **[Rust](https://www.rust-lang.org/tools/install)**, the stable toolchain, through
  `rustup`, with the C toolchain it links with (`rustup` says which: the Xcode Command Line
  Tools on macOS, `build-essential` on Debian or Ubuntu, Visual Studio's C++ build tools on
  Windows): it compiles the engine, and x264's, FFmpeg's and libopus's C.
- **[`bun`](https://bun.sh)**: it installs the browser package's locked tools, bundles its
  TypeScript sources, and runs its tests. It also builds the web page of the corpus's review
  panel (see [Testing](testing.md#the-review-panel)).

### A GPU

The engine draws with [wgpu](https://wgpu.rs): through Metal on macOS, Direct3D 12 on
Windows (WARP, on the CPU, where there is no GPU), and Vulkan on Linux. It takes the
high-performance adapter, which must be able to blend float32 render targets (a 2D view
adds up its coverage in one). Without such an adapter, rendering raises an error that says
what is missing.

On Linux without a GPU driver, Mesa's lavapipe draws on the CPU. The Linux wheels bundle it
(`scripts/release/build_lavapipe.sh` builds it, and the engine loads it itself: see
[The engine](engine.md#drawing)); an engine built from source, as here, draws with the
system's, which the workflows' Linux jobs install:

```sh
sudo apt-get install libvulkan1 mesa-vulkan-drivers
```

### Manim Community Edition

The integration corpus compares every case with Manim Community Edition's rendering of it.
CE's references are in the repository; rendering them again (a new case, or a changed
scene) needs CE, which is in its own dependency group: `uv sync --group ce` (`just sync`
leaves it out again). Its bindings to Cairo and Pango build from source where they have no
wheels (pycairo on macOS and Linux, ManimPango on Linux), so that needs those libraries:
`brew install cairo pkg-config` on macOS, `apt-get install libcairo2-dev libpango1.0-dev
pkg-config` on Debian or Ubuntu.

## Setting up the development environment

1. Clone the repository and enter it:

    ```sh
    git clone --filter=blob:none https://github.com/academa-labs/manimgx.git
    cd manimgx
    ```

    The integration corpus's reference videos make the full history large.
    `--filter=blob:none` makes a partial clone: it downloads every commit, but an old
    version of a file only when a command needs it (checking out an old commit, say).

2. Make the environment:

    ```sh
    just sync
    ```

    uv creates `./.venv`: Python, manimgx installed in editable mode with its engine
    compiled, the development tools and the docs' tools. The first sync compiles the engine
    and its dependencies (Typst, wgpu, x264), which takes a while. After that, `uv run`
    rebuilds the engine by itself whenever its Rust sources, shaders or manifests change,
    so there is no separate build step (see
    [Project management](project-management.md#rebuilding-the-engine)).
    Bun installs the browser package's development tools from `browser/bun.lock`.

3. Check that it works:

    ```sh
    just check
    just test-typescript
    just test tests/integration/test_time.py
    ```

    `just check` runs every check the repository has (see
    [Project management](project-management.md#pre-commit-configyaml-and-just-check)).
    The tests in `test_time.py` render scenes, so they use the GPU. `just test` alone runs
    the whole suite, which renders every case of the integration corpus and takes much
    longer (see [Testing](testing.md)).

4. Select the environment's interpreter in your editor. In Visual Studio Code: press
   ++ctrl+shift+p++ (++cmd+shift+p++ on macOS), run **Python: Select Interpreter**, and
   pick the one in `./.venv`. The engine's crates are a workspace,
   [`rust/`](https://github.com/academa-labs/manimgx/tree/main/rust): point rust-analyzer at `rust/Cargo.toml` if your editor
   does not find it.

## Commands

`just` lists the recipes, in four groups. The GitHub workflows run these same recipes, so a
task does the same on your machine as in CI. The recipes that run the project's tools run
them with `uv run --frozen`: in the environment, at the versions `uv.lock` pins, taking the
lockfile as it is. Run anything else the same way (`uv run --frozen python …`).

### Development

- `just sync`: make `.venv` with everything `uv.lock` pins, build the engine into it, and
  install the browser package's locked development tools.
- `just lock`: update `uv.lock` after a change to `pyproject.toml`'s dependencies.
- `just upgrade`: move `uv.lock` and `Cargo.lock` to the newest versions the manifests
  allow.
- `just licenses`: write the wheels' third-party notice
  (`LICENSE-THIRD-PARTY`) after `Cargo.lock` changes, checking that
  manimgx's `license` covers it.
- `just format`: apply ruff's fixes and format the Python with ruff (the Python in the
  Markdown too), and the browser package with Prettier.
- `just format-file <path>`: apply ruff's fixes and format with ruff, in one file or folder.
- `just check`: every check of `.pre-commit-config.yaml`, on every file. It must pass.
- `just check-typescript`: check the browser package's types and formatting.

### Testing

- `just test [args]`: the suite, in parallel; `args` go to pytest, as in
  `just test tests/integration/test_time.py -x`.
- `just test-typescript`: build and test the browser package, including its compiled worker
  and public declarations.
- `just test-coverage [args]`: the same, measuring coverage (see
  [Testing](testing.md#coverage)).
- `just combine-coverage <folder>`: one report from the coverage of several runs, as CI
  makes it.
- `just bench [REF] [args]`: the timed benchmarks, this checkout against REF's manimgx, main
  unless named (see [Testing](testing.md#benchmarks)).
- `just corpus <command>`: render, compare and review the integration corpus.
- `just review`: the corpus's review panel, at <http://127.0.0.1:8000>.

### Docs

- `just serve-docs`: the docs site at <http://localhost:8000>, rebuilt as its pages change.
- `just build-docs`: the docs site, into `site/`, as it is deployed.

See [Documentation](documentation.md#local-preview).

### Release

- `just build-wheel`: this machine's wheel, into `dist/`, tested on every supported Python.
- `just build-sdist`: the source distribution, into `dist/`.
- `just create-executable`: this machine's executable, into `dist/`, from its wheel there.
- `just build-docker-image <version>`: the Docker image of a version published on PyPI.
- `just release-notes <version>`: a version's section of the changelog.
- `just release`: tag the version in `pyproject.toml` and push the tag; the Release
  workflow publishes it.

See [Project management](project-management.md#releases).

### By hand

Two tools have no recipe, and no workflow runs them. Run them in `rust/`:

- `cargo test -p mitex-spec-gen`: whether the committed LaTeX command spec is still what
  mitex's package makes (see [The engine](engine.md#typesetting)).
- `cargo clippy`: the lints `rust/engine/Cargo.toml` sets for the engine.
