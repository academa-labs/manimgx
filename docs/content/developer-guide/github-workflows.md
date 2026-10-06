# GitHub workflows

## The problem

Some tasks must run the same way every time:

- **For every change**, pushed to `main` or proposed in a pull request: run the checks,
  and the tests on every system and Python manimgx supports; time it against the code
  before it; build the docs; publish the tests' coverage and a preview of the docs.
- **For every release:** test; build the wheels, the source distribution, the font
  packages and the executables; publish them to GitHub and PyPI, the package for the
  browser to npm, and the Docker image to ghcr.io.
- **For every issue and pull request:** a first reply to a newcomer's issue, a first
  review, and an assistant that a maintainer can ask.
- **Every week or month:** move the pinned actions and dependencies to their new releases.

Done by hand, steps get forgotten, and every run costs someone's time.

## What are GitHub Actions?

[GitHub Actions](https://docs.github.com/en/actions) runs automation on GitHub's servers
when something happens in the repository. A workflow is a file in `.github/workflows/`
that says:

1. **When it runs:** a push to `main`, a pull request, a tag, a comment, a click in
   GitHub's interface.
2. **What it does:** jobs, each a list of steps (commands, or published actions).
3. **Where it runs:** on a fresh virtual machine: Ubuntu, macOS or Windows.

A job that builds or tests begins as you would on a new machine: it checks out the
repository, installs `just` and `uv` (and, on Linux, Mesa's lavapipe to draw with when it
renders), and runs `just` recipes (see [Setup](index.md)). The
workflows run the justfile's recipes, so a task does the same in CI as on your machine.

## manimgx's workflows

manimgx has seven workflows, in
[`.github/workflows/`](https://github.com/academa-labs/manimgx/tree/main/.github/workflows).

### 1. [`test.yaml`](https://github.com/academa-labs/manimgx/blob/main/.github/workflows/test.yaml): the checks and the tests

**When it runs:**

- Every push to `main`.
- Every pull request.
- By hand, from GitHub's interface.
- When the Release workflow calls it.

**What it does**, in five jobs:

1. **Run pre-commit checks**, on Ubuntu: runs `just check`.
2. **Test the browser package**, on Ubuntu: runs `just test-typescript`, building the
   TypeScript package and checking its player, compiled worker, and public declarations.
3. **Test**, six times: on Linux, macOS and Windows, with Python 3.13 and with 3.14. Each
   tests the native source fetcher and decoder's link first, then runs `just test-coverage`
   (on Linux, with Mesa's lavapipe installed to draw with), and keeps its coverage data.
4. **Combine the coverage**, even when a test job failed: `just combine-coverage` makes one
   report of the jobs' data, and its table goes in the run's summary. The report is kept,
   with the data of a coverage badge (`badge.json`).
5. **Publish the coverage**, for `main`'s pushes and for pull requests from a branch of the
   repository: to the Worker `manimgx-coverage`
   ([`.github/deploy/coverage.jsonc`](https://github.com/academa-labs/manimgx/blob/main/.github/deploy/coverage.jsonc)).
   `main`'s report is served at <https://coverage.manimgx.academa.ai>. Each commit's report
   is also a preview deployment of its own (in the preview `main`, or `pr-<number>`), which
   the commit's "coverage" status links to.

### 2. [`benchmark.yaml`](https://github.com/academa-labs/manimgx/blob/main/.github/workflows/benchmark.yaml): the timed benchmarks

**When it runs:**

- Every push to `main` and every pull request that changes the package, the engine, the
  examples, the benchmarks or the dependencies.
- By hand, from GitHub's interface, against a commit, branch or tag you name.

**What it does**, in one job on Ubuntu: installs Mesa's lavapipe to draw with, then runs
`just bench` against the base (see [Testing](testing.md#timed-benchmarks)). A pull request is
checked out merged into its base, so its base is the merge's first parent; a push to `main`
is compared with the commit before it. There what is judged is CPU time, and the GPU is
lavapipe's, on the CPU. A workload that became slower fails the job, and every workload's
change goes in the run's summary. It is the only job that measures time: time is only
comparable on one machine at one time.

### 3. [`deploy-docs.yaml`](https://github.com/academa-labs/manimgx/blob/main/.github/workflows/deploy-docs.yaml): the docs site

**When it runs:**

- Every push to `main`.
- Every pull request, as it is opened, updated, reopened and closed.
- By hand, from GitHub's interface.

**What it does**, in four jobs:

1. **Build**, on every run except a pull request's closing: installs Mesa's lavapipe (the
   examples' videos are drawn with it), runs `just build-docs` (the narrated examples speak
   from `docs/voice/`, so the build needs no voice's key), and keeps the built `site/`
   for seven days. Deployment configuration is checked out separately from the trusted
   base commit, so the build cannot supply commands for a job with credentials to execute.
2. **Deploy**, from `main` (a push, or a run by hand): deploys what the build made to
   Cloudflare Workers with `wrangler deploy --config .github/deploy/docs.jsonc`, the
   commit's hash as its message. The `docs` environment shows the site's address,
   <https://manimgx.academa.ai>.
3. **Preview**, for a pull request from a branch of the repository: uploads the build as a
   preview named `pr-<number>`, at its own address, shown on the `docs-preview`
   environment.
4. **Delete the previews**, when a pull request closes, for both docs and coverage. An
   absent preview is already clean; authentication failures and other API errors fail
   the job.

See [Documentation](documentation.md#deployment) for how the site is served.

### 4. [`release.yaml`](https://github.com/academa-labs/manimgx/blob/main/.github/workflows/release.yaml): a release

**When it runs:**

- A pushed tag, `vX.Y.Z` (`just release`; see
  [Project management](project-management.md#releases)).
- A pull request that changes how releases are made: the release's workflows and scripts,
  the `pyproject.toml` files, the npm package, or the engine's crates' manifests and build
  scripts. It is a dry run: it builds everything, and publishes nothing.
- By hand, from GitHub's interface, on a branch: a dry run too.

**What it does**, in order. Everything is built before anything is published:

1. **Check the version.** A tag must be `v` followed by manimgx's version (in
   `pyproject.toml`), and the changelog must have a section for that
   version. A version that ends in `aN`,
   `bN` or `rcN` is a pre-release.
2. **Test**, on a tag: it runs the Test workflow.
3. **Build:** the wheels (`create-wheels.yaml`), the source distribution and the wheels'
   complete source (`just build-source`: the source distribution with every crate and each
   archive the engine's build fetches, plus the exact distribution sources retained by the
   Linux wheel jobs; the source archive waits for those platform builds; see
   [Others' sources](engine.md#others-sources)), the font packages (`just build-fonts`), and
   the executables, from the wheels (`create-executables.yaml`).
4. **Draft the GitHub release**, on a tag: it signs each file's provenance (an attestation
   of the workflow, the commit and the run that built it, which
   `gh attestation verify FILE --repo academa-labs/manimgx` checks), and drafts the release
   `manimgx X.Y.Z` with the files (the complete source too, which PyPI doesn't get), its notes
   the changelog's section for the version (`just release-notes`), then where the complete
   source is, which x264's and FFmpeg's licenses ask for.
5. **Publish to PyPI:** the font packages first, then manimgx's wheels and source
   distribution, with `uv publish`, each with its
   [PEP 740](https://peps.python.org/pep-0740/) attestation. `--check-url` skips files PyPI
   already has: the fonts are released when they change. Each package has its own GitHub
   environment and trusted publisher: `pypi` for `manimgx`, `pypi-fonts` for
   `manimgx-fonts`, and `pypi-fonts-cjk` for `manimgx-fonts-cjk`. The font jobs run as a
   matrix, each downloading only its package's distributions. Before the first release,
   register three pending publishers on PyPI with owner `academa-labs`, repository
   `manimgx`, workflow `release.yaml`, and those environment names; create the matching
   GitHub environments with release tags (`v*`) allowed. Pending publishers need distinct
   workflow/environment combinations, even when their project names differ. Publishing
   uses the workflow's OIDC token: no PyPI token is stored.
6. **Publish to npm:** the package for the browser (`just build-npm`), which installs this
   release of manimgx from PyPI, so it comes after PyPI; by trusted publishing too, with
   provenance. For the first release, before the package exists on npm, create a
   short-lived granular token with read/write access to all packages and bypass 2FA,
   and store it as `NPM_TOKEN` in the GitHub `npm` environment (allow only `v*` tags).
   The token is passed only to the publishing step. Once the package exists, configure
   its npm trusted publisher with owner `academa-labs`, repository `manimgx`, workflow
   `release.yaml`, and environment `npm`; enable direct publishing (`npm publish`),
   since the workflow does not stage releases. Then revoke the token and delete the
   GitHub secret: subsequent releases use OIDC.
7. **Publish the Docker image:** [docker/github-builder](https://github.com/docker/github-builder)
   builds `docker/Dockerfile` for the version, for `linux/amd64` and `linux/arm64`,
   with a signed provenance and SBOM (each package the image holds, with its license), and
   pushes it to `ghcr.io/academa-labs/manimgx`, tagged `X.Y.Z` and `X.Y` (a pre-release,
   `X.Y.Z` only), labeled `MIT AND GPL-3.0-or-later`: manimgx's code, and the engine, which
   x264 makes GPL-3.0-or-later as a whole. The image installs manimgx from PyPI, so it comes
   after PyPI.
8. **Publish the GitHub release:** the draft becomes public last, once PyPI, npm and
   ghcr.io have their files. Publishing alone does not lock its files or tag: that requires
   GitHub's [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
   to be enabled for the repository. This workflow attaches every file while the release
   is a draft and does not change that setting. Recorded artifact digests and provenance
   attestations verify acquired bytes; they do not enable GitHub's immutability policy.

### 5. [`create-wheels.yaml`](https://github.com/academa-labs/manimgx/blob/main/.github/workflows/create-wheels.yaml): the wheels

**When it runs:** when the Release workflow calls it (or Create executables, run by hand),
and by hand, to try a branch's wheels.

**What it does:** a job per platform (Linux x86_64 and arm64, macOS arm64 and x86_64,
Windows x86_64) runs `just build-wheel`; the macOS x86_64 wheel is cross-compiled on an
arm64 runner (`CIBW_ARCHS`), and tested there under Rosetta, and a Linux job builds Mesa's
lavapipe for its wheel first (`scripts/release/build_lavapipe.sh`). cibuildwheel builds the
platform's wheel and tests it on every
supported Python, as `[tool.cibuildwheel]` in `pyproject.toml` says (see
[Project management](project-management.md#distribution)). Each wheel is kept as
`wheel-<platform>`.

### 6. [`create-executables.yaml`](https://github.com/academa-labs/manimgx/blob/main/.github/workflows/create-executables.yaml): the executables

**When it runs:** when the Release workflow calls it, with its wheels, and by hand, when it
builds the wheels first.

**What it does:** a job per platform takes the platform's wheel and runs
`just create-executable`
([`scripts/release/create_executable.py`](https://github.com/academa-labs/manimgx/blob/main/scripts/release/create_executable.py)),
which renders a scene with the executable before it keeps it. Linux builds the launcher
inside the wheel's manylinux SDK, so both require glibc 2.28 or newer. A fresh glibc 2.28
container then runs the executable without Python, a GPU driver, network access, or an
installation cache: it uses its embedded Python and bundled lavapipe. macOS uses Metal and
Windows uses WARP. Each executable is kept as
`executable-<platform>`: `manimgx-<os>-<arch>.tar.gz`, or a `.zip` on Windows.

The interpreter is an exact Python Build Standalone release and target archive, verified
by SHA-256. The executable archive includes `build-inputs.json`, the original `PYTHON.json`,
and `LICENSE-PYTHON`; the metadata and notices also remain inside the embedded Python.
The source artifact retains the launcher's locked sources and `python-inputs.tar.xz`,
which contains the interpreter's build recipe, metadata, declared notices, and the source
inputs used to recover missing notices. This provenance archive is not the complete
corresponding source of every interpreter dependency.

Windows' interpreter also carries Microsoft's proprietary `vcruntime140.dll` and
`vcruntime140_1.dll`, recorded as `vcruntime:140` in `PYTHON.json`. These are binary
redistributables governed by [Microsoft's distribution terms](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files),
not open-source components supplied by the source archive.

### 7. [`ai.yaml`](https://github.com/academa-labs/manimgx/blob/main/.github/workflows/ai.yaml): Claude on issues and pull requests

Claude runs through [claude-code-action](https://github.com/anthropics/claude-code-action),
on Amazon Bedrock. GitHub's OIDC token is exchanged for a short-lived AWS session (for the
role in the variable `AWS_ROLE`), so no key is stored. The jobs that use it run in the `ai`
environment, and each run has a budget in dollars.

**When it runs:** an issue is opened, a comment is made on an issue or a pull request, or a
pull request is opened or marked ready for review.

**What it does**, in three ways:

- **A first reply** to an issue opened by someone outside the team (not an owner, a member
  or a collaborator, and not a bot). A model, Claude Sonnet, reads the issue, the titles of
  the open issues and the repository, and can do nothing else: it may only read the
  checked-out files, and it answers with a reply of at most 2,000 characters and up to
  three related issues. Its instructions are the workflow's own (`prompt`).
  A second job, with no model and no checkout, posts the reply: it refuses one that looks
  like it carries a credential, defuses its @-mentions, drops its images, links the related
  issues, and says that the reply is automated and that a maintainer will follow up.
- **A review** of a pull request from a branch of the repository (not a draft, and not a
  bot's), when it is opened or marked ready: Anthropic's code-review plugin, with Claude
  Opus, comments on the problems it is sure of.
- **@claude:** a maintainer mentions @claude in a new issue, or in a comment on an issue or
  a pull request, and asks for anything: an answer, a review, a change. The job first
  checks that the author can write to the repository, and stops otherwise. Claude Opus
  works in the environment `just sync` makes, and its commands run in Claude Code's
  sandbox: they reach only GitHub, PyPI, crates.io and npm, and never see the AWS session. It
  is told to follow [`AGENTS.md`](https://github.com/academa-labs/manimgx/blob/main/AGENTS.md),
  to run `just check` and the tests its change touches before it pushes, and to open a
  change as a draft pull request. On a pull request from a fork, it only reads.

## Deployment credentials

Builds and tests receive no deployment credentials. Publishing jobs use only the trusted
base commit's deployment files and the static artifacts:

- The checks, the tests and the docs' build run the repository's code (they build the
  engine and render scenes), with a token that can only read the repository. The jobs that
  get Cloudflare's API token run a pinned Wrangler on the built files (and `gh`, to set
  the coverage status). Cleanup uses the trusted base commit's `cleanup.py`. Neither
  deployment configuration nor executable code is taken from a build artifact.
- Academa's `internal/manimgx-hosting` Terraform unit owns the Worker identities,
  custom domains, GitHub environments and credentials. Each site's
  `CLOUDFLARE_API_TOKEN` can edit only that Worker; the account ID is the repository
  variable `CLOUDFLARE_ACCOUNT_ID`. Production environments allow `main`; preview
  environments also allow pull request merge refs.
- Pull requests from forks and from Dependabot get no secrets: they are built and tested,
  not previewed, and their coverage is not published.
- The first reply's model can only read, and the job that posts its reply runs no model.
- The @claude assistant is the exception: it runs the repository's code (`just sync`, the
  checks, the tests) with the AWS session at hand, and its sandbox hides the session from
  every command it runs.

Every workflow's default permissions are none (`permissions: {}`); each job asks for what
it needs.

## Details

- One run of the Test and docs workflows per pull request or branch at a time: a new
  commit to a pull request cancels its running one, while a run on `main` finishes before
  the next one begins.
- Every action is pinned to a commit, its version in a comment beside it, and wrangler's
  version is pinned in `WRANGLER_VERSION`. Dependabot moves the pins (below), and
  [zizmor](https://docs.zizmor.sh), one of the checks of `just check`, finds security
  problems in the workflows.
- The Test, docs and AI workflows share one cache of the engine's compiled Rust
  dependencies; only `main`'s runs save it.

## [`dependabot.yml`](https://github.com/academa-labs/manimgx/blob/main/.github/dependabot.yml): updates

[Dependabot](https://docs.github.com/en/code-security/dependabot) opens pull requests that
move dependencies to new releases, one per ecosystem, its updates grouped:

| Ecosystem | What moves | How often |
| --- | --- | --- |
| GitHub Actions | The workflows' pinned actions (a pinned action gets no security alerts) | Weekly |
| uv | `uv.lock`; a requirement in a `pyproject.toml` only when a release falls outside it | Monthly |
| Cargo | The engine's crates, in `Cargo.lock` | Monthly |
| pre-commit | The hooks' repositories in `.pre-commit-config.yaml` | Monthly |
| Docker | The Docker image's base, and its uv | Monthly |
| bun | The browser package's tools and the review panel's packages, grouped separately | Monthly |

A release waits a week before Dependabot proposes it: most compromised releases are caught
within days. Security updates do not wait.

## Other files in `.github/`

The [contributing guide](https://github.com/academa-labs/manimgx/blob/main/.github/CONTRIBUTING.md),
the security policy, the code of conduct, the issue forms (a bug, a feature, the docs, a
question; no blank issues) and the pull request template (a summary, a test plan, and the
use of AI). GitHub shows each where it applies.

## Learn more

- [`.github/workflows/`](https://github.com/academa-labs/manimgx/tree/main/.github/workflows):
  the workflow files.
- [GitHub Actions' documentation](https://docs.github.com/en/actions).
- [Dependabot's options](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference).
