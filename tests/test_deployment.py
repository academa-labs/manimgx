"""Deployment credentials see trusted configuration and failures stay visible."""

import io
import json
import runpy
import urllib.request
from http.client import HTTPMessage
from pathlib import Path
from typing import Never
from urllib.error import HTTPError
from urllib.request import Request

import pytest
import yaml

ROOT = Path(__file__).parents[1]
CLEANUP = ROOT / ".github/deploy/cleanup.py"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_cleanup_does_not_hide_api_failures(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    def rejected(request: Request, timeout: int) -> Never:
        raise HTTPError(request.full_url, status, "rejected", HTTPMessage(), None)

    monkeypatch.setattr(urllib.request, "urlopen", rejected)
    delete = runpy.run_path(str(CLEANUP))["delete_preview"]
    with pytest.raises(HTTPError) as error:
        delete("account", "manimgx-docs", "pr-42", "test-token")
    assert error.value.code == status


def test_cleanup_of_a_preview_that_never_existed_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(request: Request, timeout: int) -> Never:
        raise HTTPError(request.full_url, 404, "not found", HTTPMessage(), None)

    monkeypatch.setattr(urllib.request, "urlopen", missing)
    delete = runpy.run_path(str(CLEANUP))["delete_preview"]
    delete("account", "manimgx-docs", "pr-42", "test-token")


@pytest.mark.parametrize("success", [True, False])
def test_cleanup_requires_confirmation_and_deletes_only_the_named_preview(
    monkeypatch: pytest.MonkeyPatch, success: bool
) -> None:
    def respond(request: Request, timeout: int) -> io.BytesIO:
        assert request.method == "DELETE"
        assert request.full_url == (
            "https://api.cloudflare.com/client/v4/accounts/account/"
            "workers/workers/manimgx-docs/previews/pr-42"
        )
        assert request.get_header("Authorization") == "Bearer test-token"
        assert timeout == 30
        return io.BytesIO(json.dumps({"success": success}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    delete = runpy.run_path(str(CLEANUP))["delete_preview"]
    if success:
        delete("account", "manimgx-docs", "pr-42", "test-token")
    else:
        with pytest.raises(RuntimeError, match="did not confirm"):
            delete("account", "manimgx-docs", "pr-42", "test-token")


@pytest.mark.parametrize(
    ("workflow", "build", "publish", "assets"),
    [
        ("deploy-docs", "build", "deploy", "docs/site"),
        ("deploy-docs", "build", "preview", "docs/site"),
        ("test", "coverage", "publish-coverage", "htmlcov"),
    ],
)
def test_build_artifacts_cannot_supply_the_deployment_configuration(
    workflow: str, build: str, publish: str, assets: str
) -> None:
    jobs = yaml.safe_load(
        (ROOT / f".github/workflows/{workflow}.yaml").read_text(encoding="utf-8")
    )["jobs"]
    upload = next(
        step["with"]
        for step in jobs[build]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["path"].rstrip("/") == assets
    steps = jobs[publish]["steps"]
    checkout = next(
        step["with"]
        for step in steps
        if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["ref"] == "${{ github.event.pull_request.base.sha || github.sha }}"
    assert checkout["sparse-checkout"] == ".github/deploy"
    assert checkout["persist-credentials"] is False
    download = next(
        step["with"]
        for step in steps
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert download["path"] == assets
    # Even a build that puts its own .github/deploy tree in the artifact cannot
    # replace the trusted configuration at the workspace root.
    injected_config = ROOT / download["path"] / ".github/deploy/docs.jsonc"
    assert not injected_config.is_relative_to(ROOT / ".github/deploy")
