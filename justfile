# Development:
sync:
  uv sync --frozen --all-extras --reinstall-package manimgx

lock:
  uv lock

format:
  uv run --frozen --all-extras black src tests || true
  uv run --frozen --all-extras ruff check --fix src tests || true
  uv run --frozen --all-extras ruff format src tests
  cargo fmt --manifest-path rust/Cargo.toml

format-file target:
  uv run --frozen --all-extras black {{target}} || true
  uv run --frozen --all-extras ruff check --fix {{target}} || true
  uv run --frozen --all-extras ruff format {{target}}
  rustfmt {{target}}

check:
  uv run --frozen --all-extras ruff check src tests
  uv run --frozen --all-extras pyright src tests
  cargo clippy --manifest-path rust/Cargo.toml --all-targets -- -D warnings

# Testing:
test:
  uv run --frozen --all-extras pytest

update-testdata:
  uv run --frozen --all-extras pytest --update-testdata

test-coverage:
  uv run --frozen --all-extras pytest --cov=src/rendercv --cov-report=term --cov-report=html --cov-report=markdown

review-manim-comparison:
  uv run --frozen --all-extras fastapi dev tests/integration/review/app.py --port 8765

test-manim-comparison-reviewer:
  uv run --frozen --all-extras pytest tests/integration/review/e2e -v --numprocesses=1 --headed

# Utilities:
count-lines:
  wc -l `find src tests -name '*.py'`

tree:
    tree src/manimgx --gitignore

list-files:
  uv run scripts/list_files.py
  