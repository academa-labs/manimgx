"""Rendered media is reused by its inputs, and only complete outputs can be reused."""

import json
import os
import shutil
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from docs import examples

SCENE = "class Alpha(Scene):\n    pass\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def source_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    docs = tmp_path / "docs"
    for name, path in {
        "ROOT": tmp_path,
        "DOCS": docs,
        "PAGES": docs / "content",
        "README": tmp_path / "README.md",
        "SOURCE": tmp_path / "src" / "manimgx",
        "FILMS": docs / "content" / "films",
        "VOICE": docs / "voice",
        "RECORDS": docs / ".cache" / "films",
    }.items():
        monkeypatch.setattr(examples, name, path)
    write(tmp_path / "README.md", "# Welcome\n")
    write(tmp_path / "examples" / "alpha.py", SCENE)
    examples.render_context.cache_clear()
    yield tmp_path
    examples.render_context.cache_clear()


@pytest.mark.parametrize(
    "name",
    [
        "src/manimgx/scene.py",
        "rust/engine/src/render.rs",
        "rust/engine/src/stroke.wgsl",
        "rust/engine/Cargo.toml",
        "rust/ffmpeg/build.rs",
        "rust/Cargo.lock",
        "rust/mitex-spec-gen/lib.typ",
        "rust/mitex-spec-gen/spec.rkyv",
        "fonts/manimgx-fonts/src/manimgx_fonts/font.ttf",
        "docs/assets/input.svg",
        "docs/voice/line.mp3",
        "docs/examples.py",
        "docs/svg.py",
        "pyproject.toml",
        "uv.lock",
    ],
)
def test_shared_input_changes_invalidate_films(source_tree: Path, name: str) -> None:
    original = examples.render_context()
    path = write(source_tree / name, "first")
    examples.render_context.cache_clear()
    added = examples.render_context()
    assert added != original
    path.write_text("second", encoding="utf-8")
    examples.render_context.cache_clear()
    assert examples.render_context() not in {original, added}
    path.unlink()
    examples.render_context.cache_clear()
    assert examples.render_context() == original


def test_prose_styles_and_generated_files_do_not_change_the_key(
    source_tree: Path,
) -> None:
    before = examples.cache_key()
    for name in (
        "README.md",
        "docs/content/guide.md",
        "docs/content/stylesheets/theme.css",
        "docs/content/javascripts/newsletter.js",
        "docs/content/gallery/old.md",
        "docs/content/films/old.webp",
        "docs/.cache/films/old.json",
        "fonts/manimgx-fonts/src/manimgx_fonts/__pycache__/fonts.pyc",
    ):
        write(source_tree / name, "changed prose")
    examples.render_context.cache_clear()
    assert examples.cache_key() == before


def test_only_the_edited_example_changes_identity(source_tree: Path) -> None:
    write(source_tree / "examples" / "beta.py", SCENE.replace("Alpha", "Beta"))
    before = {name: e.stem for name, e in examples.scenes().items()}
    key = examples.cache_key()
    write(source_tree / "examples" / "alpha.py", SCENE.replace("pass", "value = 1"))
    after = {name: e.stem for name, e in examples.scenes().items()}
    assert after["Alpha"] != before["Alpha"]
    assert after["Beta"] == before["Beta"]
    assert examples.cache_key()["prefix"] == key["prefix"]
    assert examples.cache_key()["key"] != key["key"]


def test_gallery_is_discovered_without_generated_pages(source_tree: Path) -> None:
    assert list(examples.scenes()) == ["Alpha"]
    write(
        source_tree / "docs" / "content" / "gallery" / "stale.md",
        "```python\nclass Stale(Scene):\n    pass\n```\n",
    )
    assert list(examples.scenes()) == ["Alpha"]


def test_readme_svg_requirement_changes_the_snapshot_key(source_tree: Path) -> None:
    before = examples.cache_key()
    stem = examples.scenes()["Alpha"].stem
    write(source_tree / "README.md", f"```python\n{SCENE}```\n")
    assert examples.scenes()["Alpha"].stem == stem
    assert examples.cache_key()["key"] != before["key"]


def test_paths_and_timestamps_are_not_render_inputs(
    source_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(source_tree / "src" / "manimgx" / "scene.py", '"""Runtime docs."""\n')
    before = examples.render_context()
    os.utime(path, (1, 1))
    examples.render_context.cache_clear()
    assert examples.render_context() == before
    copied = source_tree.parent / f"{source_tree.name}-copy"
    shutil.copytree(source_tree, copied)
    monkeypatch.setattr(examples, "ROOT", copied)
    examples.render_context.cache_clear()
    assert examples.render_context() == before


def test_driver_profile_and_format_are_render_inputs(
    source_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = examples.Example(SCENE).stem
    monkeypatch.setenv("MANIMGX_DOCS_RENDER_PROFILE", "another-driver")
    examples.render_context.cache_clear()
    changed_driver = examples.Example(SCENE).stem
    assert changed_driver != before
    monkeypatch.setattr(examples, "FORMAT", "another format")
    assert examples.Example(SCENE).stem not in {before, changed_driver}


@pytest.mark.parametrize("animated", [False, True])
def test_real_renders_record_static_and_animated_outputs(
    source_tree: Path, animated: bool
) -> None:
    code = (
        "from manimgx import Scene, Square\n"
        "class Tiny(Scene):\n"
        "    def construct(self):\n"
        "        square = Square()\n"
        "        self.add(square)\n"
    )
    if animated:
        code += "        self.play(square.animate.set_opacity(0.5), run_time=0.05)\n"
    example = examples.Example(code)
    assert not examples._rendered(example, False)
    examples.render(example, readme=True)
    assert examples._rendered(example, True)
    assert (examples.FILMS / f"{example.stem}.mp4").exists() == animated
    assert not list(examples.FILMS.glob("*.json"))
    assert not list(examples.RECORDS.parent.glob("render-*"))


@pytest.fixture
def draw(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    rendered: list[str] = []

    def make(example: examples.Example, folder: Path, readme: bool) -> None:
        rendered.append(str(example.scene))
        for suffix in examples.OUTPUTS if readme else (".webp", ".mp4"):
            (folder / f"{example.stem}{suffix}").write_bytes(b"complete output")

    monkeypatch.setattr(examples, "_draw", make)
    return rendered


@pytest.mark.parametrize("damage", ["delete", "truncate", "modify"])
def test_missing_or_damaged_video_is_rendered_again(
    source_tree: Path, draw: list[str], damage: str
) -> None:
    example = examples.Example(SCENE)
    examples.render(example)
    video = examples.FILMS / f"{example.stem}.mp4"
    if damage == "delete":
        video.unlink()
    elif damage == "truncate":
        video.write_bytes(b"complete")
    else:
        video.write_bytes(b"Complete output")
    assert not examples._rendered(example, False)
    examples.render(example)
    assert examples._rendered(example, False)
    assert draw == ["Alpha", "Alpha"]


def test_failed_render_preserves_previous_complete_output(
    source_tree: Path, draw: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    example = examples.Example(SCENE)
    examples.render(example)

    def fail(example: examples.Example, folder: Path, readme: bool) -> None:
        (folder / f"{example.stem}.webp").write_bytes(b"unfinished")
        raise RuntimeError("render interrupted")

    monkeypatch.setattr(examples, "_draw", fail)
    with pytest.raises(RuntimeError, match="render interrupted"):
        examples.render(example)
    assert examples._rendered(example, False)
    assert not list(examples.RECORDS.parent.glob("render-*"))


def test_interrupted_publication_is_not_a_completed_render(
    source_tree: Path, draw: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    example = examples.Example(SCENE)
    replace = Path.replace

    def fail_record(path: Path, target: Path) -> Path:
        if path.suffix == ".json":
            raise OSError("publication interrupted")
        return replace(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_record)
        with pytest.raises(OSError, match="publication interrupted"):
            examples.render(example)
    assert (examples.FILMS / f"{example.stem}.webp").exists()
    assert not examples._rendered(example, False)
    examples.render(example)
    assert examples._rendered(example, False)


@pytest.mark.parametrize("record", ["{", "null", "[]", "{}", '{"../../outside": "x"}'])
def test_invalid_completion_record_is_a_miss(
    source_tree: Path, draw: list[str], record: str
) -> None:
    example = examples.Example(SCENE)
    examples.render(example)
    write(examples.RECORDS / f"{example.stem}.json", record)
    assert not examples._rendered(example, False)


def test_build_reuses_unchanged_scenes_and_prunes_removed_ones(
    source_tree: Path, draw: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Use the actual scheduler and filesystem with cheap fake renders in this process.
    monkeypatch.setattr(
        examples, "ProcessPoolExecutor", lambda **_: ThreadPoolExecutor(max_workers=1)
    )
    beta = write(source_tree / "examples" / "beta.py", SCENE.replace("Alpha", "Beta"))
    examples.main([])
    assert draw == ["Alpha", "Beta"]
    before = {name: e.stem for name, e in examples.scenes().items()}
    draw.clear()
    examples.main([])
    assert draw == []
    write(source_tree / "examples" / "alpha.py", SCENE.replace("pass", "value = 1"))
    examples.main([])
    assert draw == ["Alpha"]
    assert not (examples.FILMS / f"{before['Alpha']}.mp4").exists()
    assert not (examples.RECORDS / f"{before['Alpha']}.json").exists()
    draw.clear()
    beta.unlink()
    examples.main([])
    assert draw == []
    assert not (examples.FILMS / f"{before['Beta']}.mp4").exists()
    assert len(list(examples.RECORDS.glob("*.json"))) == 1
    assert set(
        json.loads(next(examples.RECORDS.glob("*.json")).read_text(encoding="utf-8"))
    ) == {
        ".webp",
        ".mp4",
    }
