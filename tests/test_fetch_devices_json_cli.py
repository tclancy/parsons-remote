"""Tests for the ``fetch_devices_json`` command line and auth header.

``main`` is what ``scripts/build-release-bundle.sh`` actually invokes, so its
exit codes are the contract that decides whether a release is cut.
"""

import json
from pathlib import Path

import fetch_devices_json as mod
import pytest

PAYLOAD = json.dumps(
    {
        "lights": [
            {
                "unit": "window",
                "label": "Window",
                "commands": {"on": {"pulses": [[1, 2]]}, "off": {"pulses": [[2, 1]]}},
            }
        ]
    }
).encode()


@pytest.fixture
def fake_fetch(monkeypatch: pytest.MonkeyPatch):
    """Replace the network round-trip with a recorded result."""

    def install(result: object) -> list[str]:
        seen: list[str] = []

        def fake(repo: str) -> tuple[bytes, str]:
            seen.append(repo)
            if isinstance(result, Exception):
                raise result
            return result  # type: ignore[return-value]

        monkeypatch.setattr(mod, "fetch_devices_json", fake)
        return seen

    return install


def test_main_writes_the_output_file(tmp_path: Path, fake_fetch) -> None:
    target = tmp_path / "devices.json"
    fake_fetch((PAYLOAD, "v0.1.0"))
    assert mod.main(["-o", str(target)]) == 0
    assert target.read_bytes() == PAYLOAD


def test_main_writes_bytes_to_stdout_when_no_output_given(capsysbinary, fake_fetch) -> None:
    fake_fetch((PAYLOAD, "v0.1.0"))
    assert mod.main([]) == 0
    assert capsysbinary.readouterr().out == PAYLOAD


def test_main_returns_1_and_writes_no_file_on_fetch_error(tmp_path: Path, fake_fetch) -> None:
    """A failed fetch must not leave a truncated or stale file behind.

    build-release-bundle.sh stages the committed copy and then overwrites it via
    this path, so a partial write here is precisely how a stale devices.json
    would reach a release.
    """
    target = tmp_path / "devices.json"
    fake_fetch(mod.FetchError("no releases"))
    assert mod.main(["-o", str(target)]) == 1
    assert not target.exists()


def test_main_passes_the_repo_through(fake_fetch, capsysbinary) -> None:
    seen = fake_fetch((PAYLOAD, "v0.1.0"))
    mod.main(["--repo", "someone/else"])
    assert seen == ["someone/else"]


def test_main_defaults_to_the_upstream_repo(fake_fetch, capsysbinary) -> None:
    seen = fake_fetch((PAYLOAD, "v0.1.0"))
    mod.main([])
    assert seen == ["tclancy/radiofrequency"]


def test_auth_header_is_omitted_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert "Authorization" not in mod._auth_headers()


@pytest.mark.parametrize("var", ["GH_TOKEN", "GITHUB_TOKEN"])
def test_auth_header_uses_either_token_variable(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv(var, "s3cret")
    assert mod._auth_headers()["Authorization"] == "Bearer s3cret"


def test_gh_token_wins_over_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gh` and Actions both set one; GH_TOKEN is the minted bot identity."""
    monkeypatch.setenv("GH_TOKEN", "minted")
    monkeypatch.setenv("GITHUB_TOKEN", "ambient")
    assert mod._auth_headers()["Authorization"] == "Bearer minted"


@pytest.fixture
def captured_request(monkeypatch: pytest.MonkeyPatch):
    """Capture the urllib Request without opening a socket."""
    box: dict[str, object] = {}

    class _Response:
        def read(self) -> bytes:
            return PAYLOAD

        def __enter__(self):
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    def fake_urlopen(request: object, **_kw: object) -> object:
        box["request"] = request
        return _Response()

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    return box


def test_asset_download_does_not_forward_the_token_across_a_redirect(
    monkeypatch: pytest.MonkeyPatch, captured_request
) -> None:
    """The asset URL 302s to a pre-signed CDN host that needs no auth.

    `Authorization` must be an *unredirected* header, or urllib hands the bearer
    token to whatever host the redirect names. Pinned because the difference is
    invisible in a passing download — both spellings fetch the file.
    """
    monkeypatch.setenv("GH_TOKEN", "s3cret")
    mod._urlopen_bytes("https://api.github.com/repos/o/r/releases/assets/1")
    request = captured_request["request"]
    assert request.get_header("Authorization") == "Bearer s3cret"
    # The distinguishing fact: it lives in unredirected_hdrs, not headers.
    assert request.unredirected_hdrs == {"Authorization": "Bearer s3cret"}
    assert "Authorization" not in request.headers


def test_asset_download_still_works_with_no_token(
    monkeypatch: pytest.MonkeyPatch, captured_request
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert mod._urlopen_bytes("https://example.invalid/asset") == PAYLOAD
    assert captured_request["request"].get_header("Authorization") is None


def test_api_read_sends_the_json_accept_header(
    monkeypatch: pytest.MonkeyPatch, captured_request
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mod._urlopen_json("https://api.github.com/repos/o/r/releases/latest")
    assert captured_request["request"].get_header("Accept") == "application/vnd.github+json"
