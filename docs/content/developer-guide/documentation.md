# Documentation

## The goal

manimgx's docs are a website with four tabs: the User Guide (Welcome, which is the README,
the Quickstart, chapters read in order, then the API reference), the Gallery, this
Developer Guide, and the Changelog. Two things make them more than pages of text:

- **Every example shows what it makes.** A code block that defines a scene appears with
  the film manimgx renders from it, rendered when the site is built, so no picture is ever
  older than the code beside it.
- **The reference tells a story, and misses nothing.** Its pages are written by hand, in
  the order of a video's parts, and render the API from the docstrings; tests keep them
  whole: every name the package documents is on a page, once.

A website is HTML, CSS and JavaScript files, served by a host. Nobody wants to write those
by hand for a docs site: the pages are Markdown, and a static site generator makes the
files.

## [Zensical](https://zensical.org): the site generator

Zensical builds a site from Markdown. It is made by the team behind Material for MkDocs,
with the same theme and Markdown extensions, and it supports some of MkDocs' plugins,
awesome-nav and mkdocstrings among them. Its settings are
[`docs/zensical.toml`](https://github.com/academa-labs/manimgx/blob/main/docs/zensical.toml), whose paths are the docs
folder's:

- **The site:** its name, URL and repository, and where each page's "edit" link goes.
- **The theme:** its features (the navbar's tabs, instant navigation, a copy button on
  code), its light and dark palettes, manimgx's own stylesheet and script, and
  `docs/overrides/`, where manimgx changes the theme's templates.
- **Markdown extensions:** admonitions, content tabs, math (rendered by KaTeX), Mermaid
  diagrams, keyboard keys, and a formatter of manimgx's own for Python blocks (below).
- **Plugins:** awesome-nav, which reads the navigation from the folders; mkdocstrings,
  which renders the API reference from the docstrings; and autorefs, which resolves links
  such as `[Circle][manimgx.Circle]`.

`zensical.toml` has no `nav`: the navigation is the folders' (below).

## The docs folder

The docs live in [`docs/`](https://github.com/academa-labs/manimgx/tree/main/docs), and
the scripts that write what is generated in them in
[`scripts/`](https://github.com/academa-labs/manimgx/tree/main/scripts):

```text
docs/
├── content/                  ← the site: every page, at the path its URL shows
│   ├── .nav.yml              ← the tabs, and the User Guide's reading order
│   ├── index.md              ← Welcome, the home page: the README, included
│   ├── user-guide/           ← the User Guide's chapters
│   ├── reference/            ← the API reference, by hand; its command-line page generated
│   ├── gallery/              ← the Gallery: its cards, and a page per film; generated
│   ├── developer-guide/      ← this guide, ordered by its own .nav.yml
│   ├── changelog.md
│   ├── films/                ← the examples' films: rendered, git-ignored
│   ├── showcase/             ← the README's wall and banner: made by scripts/showcase/
│   ├── stylesheets/, javascripts/, images/
│   └── _headers              ← the response headers Cloudflare sends
├── overrides/                ← where manimgx changes the theme: the header's logo and byline,
│                               the footer's band
├── templates/                ← how mkdocstrings shows an entry of the reference
├── zensical.toml             ← the site's settings, and llms.txt's primer for agents
├── site/                     ← the site, built: git-ignored
├── voice/                    ← what the narrated examples say: spoken once, committed
├── examples.py               ← renders the examples into content/films/, and shows each above
│                               its code while the site builds
├── svg.py                    ← a scene as an SVG that plays itself: the README's
├── links.py                  ← the README's URLs of the site as the site's paths
├── deprecated.py             ← leaves what is deprecated out of the API reference
├── films.py                  ← a picture named by its scene (a card's) shows its film's still
├── mkdocstrings.py           ← mkdocstrings finds templates/, from where the build runs
└── previews.py               ← a reference to the API previews its target, as a link does

scripts/
├── docs/
│   ├── gallery.py            ← writes the Gallery from examples/ into docs/content/gallery/
│   └── reference.py          ← writes the command line's reference, from its Typer app
└── showcase/
    ├── logo.py               ← draws the logo: the README's banner, the header's and its byline,
    │                           Academa's wordmark, the favicon
    └── wall.py               ← makes the README's wall from the example films' scenes
```

What the site's build loads (its formatter, its Markdown extensions and its griffe extension)
is in `docs/`, beside the settings that name it; what writes pages and pictures before it is
in `scripts/`.

## Navigation: folders and `.nav.yml`

The navigation is the folder tree of `docs/content/`.
[awesome-nav](https://lukasgeiter.github.io/mkdocs-awesome-nav/), which Zensical runs
natively, reads the `.nav.yml` file of a folder for the order of its pages, and a page's
title is its first heading (or the `title` of its front matter):

- [`docs/content/.nav.yml`](https://github.com/academa-labs/manimgx/blob/main/docs/content/.nav.yml)
  makes the navbar's tabs, and gives the User Guide's reading order: Welcome, the
  Quickstart, the chapters, then the Reference.
- `developer-guide/.nav.yml` orders this guide.
- The reference's navigation is the folder tree that `scripts/docs/reference.py` writes
  (below): each level's own page comes first, as its Overview.

A section's own page (`index.md`) is a page like the others, listed first in its sidebar:
Welcome, this guide's Setup, a reference level's Overview. `navigation.indexes`, which would
make it the section's title instead and leave it out of the sidebar, is off.

## Welcome: the home page

[`docs/content/index.md`](https://github.com/academa-labs/manimgx/blob/main/docs/content/index.md),
the User Guide's first page, is the README: `pymdownx.snippets` includes it
(`--8<-- "README.md"`), so the two can't drift. The README reaches the site's images and
pages by absolute URLs, for GitHub and PyPI; on the site they become its own paths
([`docs/links.py`](https://github.com/academa-labs/manimgx/blob/main/docs/links.py)), so
`just serve-docs` shows the images it built. The showcase logos and AVIFs use this repository's
raw GitHub URLs, which the same extension makes local showcase paths: the README and Welcome
page show the same files. GitHub selects the banner's light or dark source using its reader's
chosen theme. On the docs site, `javascripts/manimgx.js` follows the Zensical theme toggle,
including choices that differ from the system preference. The README's picture of its scene
ends in `#readme`: GitHub and PyPI show it, and the site, which shows the film itself above the
code, hides it (`stylesheets/manimgx.css`).

## The README

The README is the front page on GitHub and on PyPI, which render it themselves, so it is
written in plain GitHub Markdown, with absolute links (PyPI resolves no relative link). Its
images are the site's. GitHub and PyPI play no video, so what moves in them is an animated
image: SVGs that play themselves where the picture is made of paths, and AVIFs for the wall
of example films. The same banner and AVIFs appear on the docs' Welcome page, included from
the README.

- **The banner** (`showcase/logo-dark.svg` and `logo-light.svg`): the logo, which plays
  its opening once. The word ManimGX, typeset by manimgx's Typst (𝕄 as `$bb(M)$`, "anim" in
  New Computer Modern Bold, "GX" in Playwrite NO), is written in; then Manim's circle,
  square and triangle are drawn and each becomes a solid, a sphere, a cube and a pyramid,
  their projected face paths interpolated continuously by the browser. The SVG contains no
  scripts or raster frames. Its entrance plays once and then holds; a reader that requests
  reduced motion sees the finished logo immediately.
  [`scripts/showcase/logo.py`](https://github.com/academa-labs/manimgx/blob/main/scripts/showcase/logo.py)
  draws it, the header's still logo (`images/logo-*.svg`) and the favicon;
  `uv run --frozen python -m scripts.showcase.logo` draws them again.
- **The wall** (`showcase/<film>.avif`): five seconds of six example
  films, three a row, each its own image, linked to its film.
  [`scripts/showcase/wall.py`](https://github.com/academa-labs/manimgx/blob/main/scripts/showcase/wall.py)
  renders each film directly at 50 frames a second, without what it fixes in the frame
  (its titles and readouts). Each clip is cropped and resized to 320 × 180, composited onto
  a dark background, and encoded as opaque AVIF at quality 50 and speed 6, with 4:4:4 color
  to preserve thin colored lines. There are 250 frames per image, each lasting 20 ms.
  Each file must stay below 500,000 bytes,
  and the complete wall below 1,200,000 bytes; the generator validates the whole staged
  set before replacing any published file. The README points directly to
  `raw.githubusercontent.com/academa-labs/manimgx/main/docs/content/showcase/`.
  The docs resolve that exact prefix to their local `/showcase/` assets. There is one image
  per film and one shared wall, in both places and on both color schemes. The AVIFs are
  committed; `uv run --frozen python -m scripts.showcase.wall` makes them again with
  Pillow's AVIF encoder.
- **The chart** (`images/benchmark-light.svg` and `benchmark-dark.svg`): the benchmark, as
  a race; `scripts/benchmark/chart.py` draws it from `scripts/benchmark/results.json`.
- **The scene's film** (`films/readme-<scene>.svg`): `docs/examples.py` records the README's
  scene frame by frame with
  [`docs/svg.py`](https://github.com/academa-labs/manimgx/blob/main/docs/svg.py), which
  reads the view and each path's paint at every frame and writes them as an SVG that
  plays itself (SMIL): a README scene is made of paths, whose shapes hold still.

## Examples: films rendered from the code

[`docs/examples.py`](https://github.com/academa-labs/manimgx/blob/main/docs/examples.py)
renders the examples before the site is built:

1. It gathers the Python blocks (fenced as `python` or `py`) of the pages, of the README
   and of the docstrings in `src/manimgx/`, together with the source films in `examples/`,
   and keeps those that define a
   scene: a class whose base's name ends in `Scene` (the block's last, if it defines several).
2. It renders each scene at 1280 × 720 and 60 frames per second, the films' own rate, in a
   process of its own (an example may change the configuration: a 9:16 one renders tall),
   into `docs/content/films/`: a still of its last frame with anything on it, and a video
   too if anything moves.
3. A film is named after its scene and a digest of its code, render settings and shared
   inputs: Python and Rust sources, shaders, locked dependencies, fonts, voice recordings,
   rendering helpers and the rendering environment. A prose or stylesheet edit reuses
   every film; editing a standalone example renders that example again. Shared inputs are
   hashed conservatively, including Python docstrings, so changing one invalidates all
   films. The keys depend on file contents, not Git history or modification times.
4. Each render finishes in a temporary directory. Its output files are published with a
   completion record in `docs/.cache/films/`, written last, that names the files and their
   checksums. A missing or damaged file is rendered again. Static scenes deliberately
   produce only a poster; animations also produce a video. Outputs of removed examples
   are deleted.

`just render-docs` renders the examples, and `just build-docs-pages` generates the Gallery
and command-line reference and builds the HTML from those films. `just build-docs` does
both. Rendering reads `examples/` directly, so it does not need generated Gallery pages.
`just render-docs --jobs 2` limits concurrent render processes; source paths may follow it.

CI restores the films and completion records with GitHub Actions cache, validates them,
renders what is missing, and saves the completed set before building the pages. Main
writes the shared cache; pull requests can read it without deployment credentials. The
cache key includes the shared renderer fingerprint and the inventory of requested scenes;
a compatible older snapshot supplies unchanged films when one example changes. A cache
miss rebuilds normally: caches are an optimization and may be evicted.

CI records its Rust compiler and installed Vulkan driver versions in
`MANIMGX_DOCS_RENDER_PROFILE`; Python version, OS and architecture are always part of the
fingerprint. Local builds also include their machine and OS version, keeping their GPU
output separate. Examples must be self-contained and deterministic (seed random
generators); shared files they read belong in `docs/assets/` or `docs/voice/`, which are
fingerprinted. Add any new shared rendering input to `INPUTS` in `docs/examples.py`.

While the site builds, `fence`, the formatter that `zensical.toml` gives Python blocks,
puts each block's film above its code. `show="code"` shows the code alone, and
`show="film"` the film alone: two blocks with the same code let a page put words between
a program and its video (the Basics shows a command there). On the page, a film plays
while it is on screen, unless the reader prefers reduced motion.

So a scene's name is its film's, and must be unique across the docs; a failed example fails
the build. A block meant to show code without a film defines no scene. Given paths,
`python -m docs.examples docs/content/user-guide` renders only the examples written under
them.

A narrated example (`self.say(…)`) says what `docs/voice/` keeps, since the site is built with
no voice's key: a new or changed line is spoken once, by a render with `FAL_KEY`, and its
audio and words are committed with it.
[`tests/docs/test_examples.py`](https://github.com/academa-labs/manimgx/blob/main/tests/docs/test_examples.py)
fails until they are.

A film is encoded for the web (x264's `slow` preset at CRF 28): a tenth of the size of a
render's default (`ultrafast`, 18), alike to the eye, made in the same time.

## The Gallery

[`scripts/docs/gallery.py`](https://github.com/academa-labs/manimgx/blob/main/scripts/docs/gallery.py)
writes the Gallery from `examples/` alone, before the examples are rendered: a page of cards,
one for each film, and a page for each film. What it says is in
[`examples/README.md`](https://github.com/academa-labs/manimgx/blob/main/examples/README.md),
which lists every example once:

- **The first page:** the README's introduction (its first paragraph), then its groups, in
  their order, each a grid of cards. A card shows the film's still
  (`![](film:HopfFibration)`, which `docs/films.py` resolves), its title and its first
  sentence. The whole card is a link to the film's page.
- **A film's page:** its line in the README,
  `- [The Hopf fibration](hopf_fibration.py): The 3-sphere is made of circles…`, gives its
  title and its words, a sentence or two. Then the film, and its code, the file, folded under
  it: a block marked `fold`, whose film `docs/examples.py` renders as it renders every
  example's. The file's docstring tells the mathematics, for the reader who opens the code.
- **Its navigation:** `gallery/.nav.yml`, written with the pages: the README's groups, so
  that a film's page lists every film beside it.

The pages are generated (`content/gallery/`, git-ignored), so an example added to `examples/`
and its README is in the Gallery at the next build.
[`tests/docs/test_gallery.py`](https://github.com/academa-labs/manimgx/blob/main/tests/docs/test_gallery.py)
checks that every example has its card and its page, and that a card says one short sentence.

## The API reference

**The problem:** a reference generated from the package lists what the package has, module
by module: it misses no name, but it tells no story. A reader finds every class and learns
nothing of how the parts of a video fit together, and reads every name Manim CE kept, useful
or not. A reference written by hand tells the story, but misses the names added after it, and
keeps the names removed since.

**The solution:** the reference is written by hand, as a story, and renders the API from the
package; tests keep the two together.

- **Its story:** a video is a scene, which shows mobjects, which animations change and
  updaters keep, as the camera sees them, with sound, until rendering makes the video. Each
  section of `docs/content/reference/` tells one part, in Learn's order: Scenes, Mobjects,
  Animations, Updaters, Camera and 3D, Sound, Rendering. A section opens with what its part
  is, then a card for each of its pages. A page is a topic, not a class: "Lines and arrows"
  tells Line, then Arrow, then Vector, then the tips, as one story.
- **Its API:** a page writes its story in prose, and renders each object in it with
  mkdocstrings' `::: manimgx.Circle` block, from its docstring, in the order the story needs.
  A class's block shows its members, unless the page lists some, or none (`members: false`),
  to show them under headings of its own (Mobject's, on six pages). A member a public class
  takes from a private base (`_Grid`'s, Matrix's and Table's) is listed in the block's
  `inherited_members`.
- **What it leaves out:** a class, a function or a property decorated with `@deprecated`
  (PEP 702): a name kept only for code written for Manim CE, which ty flags where it is
  used.
  [`docs/deprecated.py`](https://github.com/academa-labs/manimgx/blob/main/docs/deprecated.py)
  removes each one as griffe loads the package, so it has no entry, its class does not list
  it, and a link to it does not resolve. A deprecated class stays in its module, under no
  other name, for the classes made from it to take their constructor from: no page shows it,
  nor what they take from it. The extension reads the decorator in the source, as ty does (a
  property's, on its getter). An attribute, a constant or a type alias can't carry
  the decorator: the few that no scene needs are listed in
  [`tests/docs/test_reference.py`](https://github.com/academa-labs/manimgx/blob/main/tests/docs/test_reference.py)'s
  `UNDOCUMENTED`.
- **What keeps it whole:** `tests/docs/test_reference.py` finds what the package documents
  (every name it exports, and every documented member of an exported class) and what the
  pages render, and fails on a name no page shows, one shown twice, or one deprecated. The
  site's strict build fails on a block or a link whose object is gone.
  [`tests/docs/test_hidden.py`](https://github.com/academa-labs/manimgx/blob/main/tests/docs/test_hidden.py)
  type-checks every example the docs show, `deprecated` an error, so no page teaches a
  hidden name.
- **Cards:** a section's page shows its pages as cards: a film's still, the page's name and
  a sentence, the whole card a link. A card names its film by its scene,
  `![](film:LinesAndArrows)`, which
  [`docs/films.py`](https://github.com/academa-labs/manimgx/blob/main/docs/films.py)
  resolves to the film the examples' renderer made, whatever its digest. Each page opens with
  such a film, its code folded under it: a card's picture, and the page's.

The pages are rendered by [mkdocstrings](https://mkdocstrings.github.io), which reads the
docstrings with [griffe](https://mkdocstrings.github.io/griffe/).
[`docs/templates/python/material/`](https://github.com/academa-labs/manimgx/tree/main/docs/templates/python/material)
shows an entry as a scene writes it:

- **Its film first:** the docstring's example, its code folded under it, then what it is.
- **Its call, without types:** `m.Circle(radius=None, …)`, `self.play(…)`,
  `circle.surround(…)`, `Circle.from_three_points(…)`, `class MyScene(m.Scene):`; an
  editor shows the types.
- **What it takes, in words:** each parameter's name and description. Its `**kwargs`, a
  `TypedDict`, is opened by vocabulary: the keywords one class owns are listed on its
  entry ("A [Matrix][manimgx.Matrix]'s keywords …", its docstring says) and linked from
  every other; the style, tip, animation and transform keywords are one link each, to where
  they are told.
- **Its source, one click away:** a Source button that opens the code where it is defined.

A module's docstring is not shown: in manimgx it is a note for the developers who change the
module. mkdocstrings reads the `custom_templates` setting from the working directory, and
Zensical passes it on as written, not made absolute from the settings' folder as MkDocs
does; [`docs/mkdocstrings.py`](https://github.com/academa-labs/manimgx/blob/main/docs/mkdocstrings.py)
makes it absolute before mkdocstrings reads it.

## Instant previews

Rest the pointer on a link to a page of the site, and a preview of its target opens. A
reference to the API previews too: its name, signature, bases and summary, as an editor's
hover shows them. So the summary line of a docstring is also what its previews show.

- **Which links preview:** Zensical's `preview` extension marks every link to a page of the
  site (`targets.include = ["*"]` in `docs/zensical.toml`), but not a heading's `¶` or a
  footnote. A reference to the API is an `<autoref>` tag until Zensical resolves it, after
  the extension has run. So
  [`docs/previews.py`](https://github.com/academa-labs/manimgx/blob/main/docs/previews.py)
  marks each of these tags, and the link keeps the mark. It also takes the mark off a
  card's link: the card shows its page's still, name and words already, and a preview would
  cover the cards beside it.
- **What a preview shows:** the theme shows the target heading and the text after it, up to
  the next heading. `stylesheets/manimgx.css` limits the preview of an API object to its
  name, signature, bases and summary, and the preview of a module to its members' names and
  summaries. No icon marks a link that previews, because every link to the site does.
- **After a change to a Markdown extension in `docs/`:** delete `docs/.cache`. Zensical's
  cache does not see a change in an extension's code, so a build reuses the pages it made
  before.

## The command line's reference

[`scripts/docs/reference.py`](https://github.com/academa-labs/manimgx/blob/main/scripts/docs/reference.py)
writes the command line's reference,
[`reference/rendering/command-line.md`](../reference/rendering/command-line.md), from the
Typer app itself (`typer manimgx.cli utils docs`): the one page of the reference that is
generated. It is always the app's, and it is not committed.

## Docstrings

The reference is made from the docstrings, so they are written for readers of the docs:

- They follow the
  [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings):
  a summary line, then `Args:`, `Returns:`, `Raises:` and `Examples:` sections.
- An example is a Python block, under `Examples:`, that defines a scene. It is rendered like
  the pages' examples, so its scene's name is unique across the docs
  (`TipableVMobjectAddTipExample`, say).
- A docstring links to another object as `[text][manimgx.path.to.it]`, an autoref. The
  object must be on a page of the reference: the site's strict build fails on a link whose
  target no page shows. A class's keywords are linked by their class
  (`[number line keywords][manimgx.NumberLine]`), whose entry lists them.

## Markdown for agents

An agent reads Markdown better than a page's HTML. Zensical's
[`llmstxt` plugin](https://zensical.org/docs/compatibility/mkdocs/plugins/#llmstxt), set in
`[project.plugins.llmstxt]` of
[`docs/zensical.toml`](https://github.com/academa-labs/manimgx/blob/main/docs/zensical.toml),
writes three things:

- **Each page's Markdown, beside the page:** `/user-guide/quickstart/index.md` beside
  `/user-guide/quickstart/`. The plugin converts the page as it is built, so the Markdown
  has what the page shows: the examples' code, the admonitions, the reference's signatures.
  A page's one action, Copy as Markdown (`content.action.copy`), copies it.
- **`llms.txt`,** at the site's root, <https://manimgx.academa.ai/llms.txt>, which the
  README tells an agent to follow. First, a primer for an agent asked to make a video with
  manimgx: how to install it, a scene, `inspect` then `render`, and a cheat sheet of the API.
  Then a list of every page's Markdown, by section.
- **`llms-full.txt`:** every page's Markdown, in one file.

The primer is the plugin's `markdown_description`, written by hand, so
[`tests/docs/test_llms.py`](https://github.com/academa-labs/manimgx/blob/main/tests/docs/test_llms.py)
checks it against the API: its scene runs, and every name it teaches exists. The plugin
writes the Markdown only of the pages its sections name, so the sections name every page
with patterns (`user-guide/*.md`), and the test checks that each page matches one: a page in
a new folder needs a pattern.

## The agent skill

[`skills/manimgx/SKILL.md`](https://github.com/academa-labs/manimgx/blob/main/skills/manimgx/SKILL.md)
is manimgx's [agent skill](https://agentskills.io). `npx skills add academa-labs/manimgx`
and `gh skill install academa-labs/manimgx` find it by its path, `skills/<name>/SKILL.md`,
and copy its folder into an agent's skills, so the folder stays where it is. The installers
read its front matter, so
[`tests/docs/test_skill.py`](https://github.com/academa-labs/manimgx/blob/main/tests/docs/test_skill.py)
checks it against the [specification](https://agentskills.io/specification): the name is
its folder's, and the description is 1 to 1,024 characters.

## The changelog

[`docs/content/changelog.md`](https://github.com/academa-labs/manimgx/blob/main/docs/content/changelog.md)
follows [Keep a Changelog](https://keepachangelog.com). The first release, 0.1.0, has no
changes to list: its section says only that it is the first. After it, a change a user would
notice adds a line under "Unreleased", in the same pull request. A release moves those lines
into its version's section, which becomes the release's notes (see
[Project management](project-management.md#releases)).

## Local preview

```sh
just serve-docs
```

Writes the Gallery, renders the missing films, writes the reference, then serves the site at
<http://localhost:8000> and rebuilds it as its pages change. An example that fails to render
is reported and served without its film. A block added while it serves
has no film until the examples are rendered again, and a name added to or removed from the
package's exports shows in the reference once `just serve-docs` runs again: the reference's
pages are written before it serves.

```sh
just build-docs
```

Writes the Gallery, renders the examples, writes the reference, and builds the site into
`docs/site/` with `--strict`: a warning, such as a link to a page or a name that does not
exist, fails the build. This is what CI deploys.

Zensical runs as `python -m zensical`, from the repository's root, which it puts on the
path, so it can import `docs.examples.fence`; `--config-file docs/zensical.toml` gives it the
site.

## Deployment

The site is static files, served by
[Cloudflare Workers](https://developers.cloudflare.com/workers/static-assets/) as static
assets: no Worker script runs, and every request is answered from the files in `site/`.
[`.github/deploy/docs.jsonc`](https://github.com/academa-labs/manimgx/blob/main/.github/deploy/docs.jsonc)
configures it:

- The Worker, `manimgx-docs`, serves the site at its domain,
  [manimgx.academa.ai](https://manimgx.academa.ai).
- A page is a folder (`changelog/index.html`): a request for `/changelog` is redirected to
  `/changelog/`.
- A path that matches nothing gets the nearest `404.html`, with status 404.
- `docs/content/_headers` is copied to the site's root, where Cloudflare reads it (it is
  never served): security headers for every page, long caching for the theme's bundles
  (their names change with their content), and `noindex` on `workers.dev` hosts.

Academa's `internal/manimgx-hosting` Terraform unit provisions the Worker identity,
custom domain and deployment credential. It also provisions the coverage report's
Worker and domain. Wrangler publishes assets and previews; it leaves domain ownership
to Terraform. The account ID is a GitHub repository variable, and each site's deployment
token is installed in its production and preview environments by Terraform.

The workflow [`deploy-docs.yaml`](https://github.com/academa-labs/manimgx/blob/main/.github/workflows/deploy-docs.yaml)
builds the site on every push and pull request, deploys it from `main`, and previews each
pull request from a branch of the repository at its own address,
`pr-<number>-manimgx-docs.<account subdomain>.workers.dev`. See
[GitHub workflows](github-workflows.md#3-deploy-docsyaml-the-docs-site).

## Learn more

- [Zensical's documentation](https://zensical.org/docs/): setup, authoring, and its
  compatibility with Material for MkDocs.
- [awesome-nav's documentation](https://lukasgeiter.github.io/mkdocs-awesome-nav/): what a
  `.nav.yml` can say.
- [mkdocstrings' Python handler](https://mkdocstrings.github.io/python/): the options in
  `zensical.toml`.
- [Cloudflare's static assets](https://developers.cloudflare.com/workers/static-assets/):
  routing, headers, previews.
