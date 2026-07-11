# Quickstart

There are two ways to start. Choose one.

## With an AI agent

Paste this into Claude Code or Codex:

``` { .text .mx-prompt }
Follow https://manimgx.academa.ai/llms.txt to make me a short animation of a square turning into a circle, and open it.
```

That's it. The agent installs manimgx, writes the code, makes the video and opens it. To
get a different video, change the words after "make me". If the agent asks to use the
network or the GPU, allow it.

## By hand

### 1. Install manimgx

=== "uv"

    If you don't have [uv](https://docs.astral.sh/uv/), install it:

    === "macOS and Linux"

        ```sh
        curl -LsSf https://astral.sh/uv/install.sh | sh
        ```

    === "Windows"

        ```powershell
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        ```

    Then close the terminal and open a new one, so that it finds uv. Make a folder for
    your videos, with manimgx in it (uv also installs Python 3.14 if you don't have it):

    ```sh
    uv init --bare --python 3.14 my-videos
    cd my-videos
    uv add manimgx
    ```

=== "pip"

    You need Python 3.13 or 3.14. Make a folder for your videos, with a virtual
    environment, and install manimgx in it:

    ```sh
    mkdir my-videos
    cd my-videos
    python3 -m venv .venv      # Windows: py -m venv .venv
    source .venv/bin/activate  # Windows: .venv\Scripts\activate
    pip install manimgx
    ```

    If Windows' PowerShell refuses to run the activate script, allow it once with
    `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.

### 2. Set up your editor

Set up [ty](https://docs.astral.sh/ty/) in your editor. ty checks your code as you type.
It completes manimgx's names, shows what each one does, and underlines many of your
mistakes before you make a video.

=== "VS Code"

    Install the [ty extension](https://marketplace.visualstudio.com/items?itemName=astral-sh.ty).
    Cursor, Windsurf and the other editors made from VS Code have it in their Extensions
    view too. Then open your folder, `my-videos`, with **File > Open Folder**.

=== "Zed"

    Zed includes ty. To turn it on, open your settings file (++cmd+alt+comma++ on a Mac,
    ++ctrl+alt+comma++ on Windows and Linux), and paste these lines right after its first
    `{`:

    ```json
      "languages": {
        "Python": {
          "language_servers": ["ty", "!basedpyright", "..."]
        }
      },
    ```

    Then open your folder, `my-videos`, with **File > Open**.

ty finds manimgx in the folder's `.venv`, which step 1 made.

### 3. Write a scene

In your folder, make a file named `scene.py`, and write this code in it:

```python title="scene.py"
import manimgx as m


class SquareToCircle(m.Scene):
    def construct(self) -> None:
        square = m.Square(side_length=3, color=m.BLUE, fill_opacity=0.5)
        circle = m.Circle(radius=1.6, color=m.PINK, fill_opacity=0.5)
        self.play(m.Create(square))
        self.play(m.Transform(square, circle))
        self.wait()
```

### 4. Preview it

Open your editor's terminal (++ctrl+grave++), and run:

=== "uv"

    ```sh
    uv run manimgx preview scene.py
    ```

    With uv, start every `manimgx` command with `uv run`. The rest of these docs write
    the commands without it.

=== "pip"

    ```sh
    manimgx preview scene.py
    ```

    In a new terminal, activate the environment first, as in step 1.

A window plays your scene. Put it next to your editor. Each time that you save
`scene.py`, the window plays the new version. Try it: change `m.PINK` to `m.YELLOW`, and
save.

### 5. Make the video

=== "uv"

    ```sh
    uv run manimgx render scene.py
    ```

=== "pip"

    ```sh
    manimgx render scene.py
    ```

manimgx writes the video, `SquareToCircle.mp4`, next to `scene.py`. It's the video above
the code in step 3. For a tall video (Shorts, Reels, TikTok), add `-r 1080x1920`.

You are ready. Next, [The basics](the-basics.md) explains how a scene makes a video.
