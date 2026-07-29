"""End-to-end tests for ``scripts/build-release-bundle.sh``.

The tarball's *shape* is a cross-repo contract: the homelab `products` role
(tclancy/homelab#269) downloads `parsons-remote-<tag>.tar.gz`, verifies a pinned
SHA256, unpacks it into `~/sources/parsons-remote-releases/<tag>/` and symlinks
`current` at the result. Nothing in this repo would notice if that shape drifted,
so it gets an actual build against a stubbed GitHub API rather than a set of
assertions about the script's text.

Marked ``integration`` because these shell out; the script's own test fence
deselects the marker so the fence cannot recurse into itself.
"""

import hashlib
import http.server
import json
import os
import subprocess
import tarfile
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "build-release-bundle.sh"

pytestmark = pytest.mark.integration

UPSTREAM_DEVICES = json.dumps(
    {
        "lights": [
            {
                "unit": "hall",
                "label": "Hall",
                "position": 1,
                "commands": {
                    "on": {"pulses": [[1, 2]], "repeat_count": 15},
                    "off": {"pulses": [[2, 1]], "repeat_count": 15},
                },
            }
        ]
    },
    indent=2,
).encode()


class _StubGitHub(http.server.BaseHTTPRequestHandler):
    """Serves just enough of the releases API to satisfy a real fetch."""

    def do_GET(self) -> None:
        # Matched strictly from the root, not with `endswith`: the no-release
        # test drives a bogus API root through here and needs a real 404. A
        # loose suffix match served it a healthy release and the test passed
        # while proving nothing.
        if self.path.startswith("/repos/") and self.path.endswith("/releases/latest"):
            body = json.dumps(
                {
                    "tag_name": "v9.9.9",
                    "assets": [
                        {
                            "name": "devices.json",
                            "url": f"http://{self.server.server_address[0]}"
                            f":{self.server.server_address[1]}/asset",
                        }
                    ],
                }
            ).encode()
        elif self.path == "/asset":
            body = UPSTREAM_DEVICES
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        """Silence the default stderr access log."""


@pytest.fixture(scope="module")
def stub_github():
    server = http.server.HTTPServer(("127.0.0.1", 0), _StubGitHub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _run(env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = dict(os.environ, **env_overrides)
    # The dispatch bot injects git config through these; they leak into the
    # subprocess and are irrelevant here.
    for var in list(env):
        if var.startswith("GIT_CONFIG"):
            del env[var]
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


# Module-scoped: every consumer is read-only against the finished artifact, and
# each build runs a nested pytest fence, so a function-scoped fixture would pay
# that cost six times per suite run.
@pytest.fixture(scope="module")
def built(stub_github: str):
    """Build a real bundle against the stub and hand back the artifact paths."""
    tag = "v0.0.0-test"
    result = _run({"TAG": tag, "GITHUB_API_URL": stub_github, "UPSTREAM_REPO": "stub/upstream"})
    assert result.returncode == 0, f"build failed:\n{result.stdout}\n{result.stderr}"
    bundle = REPO_ROOT / "dist" / f"parsons-remote-{tag}.tar.gz"
    checksum = Path(f"{bundle}.sha256")
    yield bundle, checksum
    bundle.unlink(missing_ok=True)
    checksum.unlink(missing_ok=True)


def test_bundle_and_checksum_are_produced(built) -> None:
    bundle, checksum = built
    assert bundle.is_file()
    assert checksum.is_file()


def test_bundle_has_exactly_one_top_level_www_directory(built) -> None:
    """homelab#269 unpacks into a per-version dir and symlinks `current` at it.

    A tarball that spilled its files at the top level would scatter them across
    that directory and make the unpack non-idempotent.
    """
    bundle, _ = built
    with tarfile.open(bundle) as archive:
        tops = {Path(name).parts[0] for name in archive.getnames()}
    assert tops == {"www"}


def test_bundle_carries_the_upstream_devices_json_not_the_committed_one(built) -> None:
    """The whole point of the extraction: the committed copy must not ship."""
    bundle, _ = built
    with tarfile.open(bundle) as archive:
        member = archive.extractfile("www/devices.json")
        assert member is not None
        shipped = member.read()
    assert shipped == UPSTREAM_DEVICES
    assert shipped != (REPO_ROOT / "www" / "devices.json").read_bytes()


def test_bundle_contains_every_committed_asset(built) -> None:
    bundle, _ = built
    with tarfile.open(bundle) as archive:
        shipped = {name.removeprefix("www/") for name in archive.getnames() if name != "www"}
    expected = {path.name for path in (REPO_ROOT / "www").iterdir()}
    assert expected <= shipped, f"missing from the bundle: {expected - shipped}"


def test_bundle_has_no_macos_appledouble_sidecars(built) -> None:
    """`COPYFILE_DISABLE=1` in the script is what stops these; pin it.

    Without it a bundle built on Tom's Mac unpacks `._app.js` and friends next to
    every real file on the homelab.
    """
    bundle, _ = built
    with tarfile.open(bundle) as archive:
        junk = [n for n in archive.getnames() if Path(n).name.startswith("._")]
    assert not junk, f"AppleDouble sidecars in the bundle: {junk}"


def test_checksum_file_matches_the_bundle_and_is_shasum_c_format(built) -> None:
    bundle, checksum = built
    digest, _, name = checksum.read_text().strip().partition("  ")
    assert digest == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert name == bundle.name, "the checksum must name the bare filename, not a path"
    verify = subprocess.run(
        ["shasum", "-a", "256", "-c", checksum.name],
        cwd=bundle.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr


def test_build_fails_when_upstream_has_no_release(stub_github: str) -> None:
    """Fail-closed is the decision in ADR-001 — prove it, don't assert the prose.

    Points the fetch at a path the stub 404s so the real error path runs.
    """
    bundle = REPO_ROOT / "dist" / "parsons-remote-v0.0.0-missing.tar.gz"
    bundle.unlink(missing_ok=True)  # a leftover would make the last assert lie
    result = _run(
        {
            "TAG": "v0.0.0-missing",
            "GITHUB_API_URL": f"{stub_github}/nope",
            "UPSTREAM_REPO": "stub/upstream",
        }
    )
    assert result.returncode != 0
    assert "no published releases" in result.stderr
    assert not bundle.exists()


def test_build_rejects_an_unknown_argument() -> None:
    env = dict(os.environ, TAG="v0.0.0-test")
    for var in list(env):
        if var.startswith("GIT_CONFIG"):
            del env[var]
    result = subprocess.run(
        ["bash", str(SCRIPT), "--publsh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unknown argument" in result.stderr


def test_build_refuses_to_run_without_a_tag() -> None:
    """CI passes `github.ref_name`; locally a typo'd env var must not silently
    produce an untagged bundle."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TAG", "GIT_CONFIG"))}
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_dir_without_tags(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "TAG env var not set" in result.stderr


def tmp_dir_without_tags() -> str:
    """Run from a directory with no git tags so `git describe` finds nothing.

    The script cd's to its own repo root regardless, so this only controls where
    bash starts; the tag lookup still runs against this checkout. Guard against a
    tagged checkout making the test meaningless.
    """
    described = subprocess.run(
        ["git", "describe", "--tags", "--exact-match", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if described.returncode == 0:
        pytest.skip(f"HEAD is tagged ({described.stdout.strip()}); the no-TAG path cannot run")
    return str(REPO_ROOT)
