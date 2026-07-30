"""The README, included as the Welcome page, reaches the site's own images and pages on the
site it is on (`docs/links.py`), so `just serve-docs` shows the images it built."""

from pathlib import Path

import pytest

README = Path(__file__).parents[2] / "README.md"


def test_the_readme_reaches_the_site_it_is_on() -> None:
    markdown = pytest.importorskip("markdown")  # the docs group's
    from docs import links

    html = markdown.markdown(
        README.read_text(encoding="utf-8"),
        extensions=["md_in_html", "pymdownx.superfences", links.makeExtension()],
    )
    site = f"https://{links.HOST}"
    for attribute in ("src", "srcset", "href", "poster"):
        assert f'{attribute}="{site}' not in html
    # the banner, the logo on each ground
    assert 'srcset="/showcase/logo-dark.svg"' in html
    assert 'src="/showcase/logo-light.svg"' in html
    # the wall's films, and the scene's film on each ground
    assert 'srcset="/showcase/hopf_fibration.avif"' in html  # on a low-density screen
    assert 'src="/showcase/hopf_fibration@2x.avif"' in html
    assert 'srcset="/films/readme-Hopf.svg"' in html
    assert 'src="/films/readme-Hopf-light.svg#readme"' in html
    # a URL written as text, which an agent is told to follow, stays as it is
    assert f"Follow {site}/llms.txt" in html


def test_only_the_site_s_own_urls_become_paths() -> None:
    pytest.importorskip("markdown")
    from docs import links

    site = f"https://{links.HOST}"
    tags = (
        f'<a href="{site}">'
        f"<img src='{site}/a.svg#readme' srcset=\"{site}/a.svg 1x, {site}/b.svg 2x\">"
        f'<img src="https://img.shields.io/badge/docs-{links.HOST}-blue">'
        f'<code>&lt;img src="{site}/c.svg"&gt;</code>'
    )
    assert links.paths(tags) == (
        '<a href="/">'
        "<img src='/a.svg#readme' srcset=\"/a.svg 1x, /b.svg 2x\">"
        f'<img src="https://img.shields.io/badge/docs-{links.HOST}-blue">'
        f'<code>&lt;img src="{site}/c.svg"&gt;</code>'
    )
