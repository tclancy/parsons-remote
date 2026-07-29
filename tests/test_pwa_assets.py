"""Integrity checks on the static assets in ``www/``.

There is no build step, so nothing else would catch a renamed or dropped file
until it 404s on a phone. Each test here pins a reference that a human editing
the PWA can silently break:

* the service worker's precache list (``cache.addAll`` rejects *atomically*, so
  one bad entry disables offline mode entirely — and on a warm cache the app
  looks fine while it happens),
* the manifest's icon list,
* ``index.html``'s own ``href``/``src`` references,
* the shape of ``devices.json`` that ``app.js`` dereferences.
"""

import json
import re
from pathlib import Path

import pytest
from fetch_devices_json import FetchError, validate

#: Paths the app is allowed to reference without a matching file on disk,
#: because Caddy or the browser resolves them rather than the filesystem.
VIRTUAL_PATHS = {"/"}


def _resolve(www: Path, reference: str) -> Path:
    """Map a URL path or relative href to the file that should satisfy it."""
    return www / reference.lstrip("/")


def _sw_precache_list(www: Path) -> list[str]:
    """Extract the ``ASSETS`` array literal from ``sw.js``."""
    source = (www / "sw.js").read_text()
    match = re.search(r"var\s+ASSETS\s*=\s*\[(.*?)\]", source, re.DOTALL)
    assert match, "sw.js no longer declares a `var ASSETS = [...]` precache list"
    return re.findall(r'"([^"]+)"', match.group(1))


def _index_local_references(www: Path) -> list[str]:
    """Every local ``href``/``src`` in ``index.html`` (external URLs skipped)."""
    source = (www / "index.html").read_text()
    found = re.findall(r'(?:href|src)="([^"]+)"', source)
    return [ref for ref in found if not re.match(r"^(?:https?:)?//|^data:|^#", ref)]


def test_service_worker_precaches_only_files_that_exist(www: Path) -> None:
    missing = [
        entry
        for entry in _sw_precache_list(www)
        if entry not in VIRTUAL_PATHS and not _resolve(www, entry).is_file()
    ]
    assert not missing, (
        f"sw.js precaches files that do not exist: {missing}. cache.addAll rejects "
        "atomically, so this disables offline mode for every installed client."
    )


def test_service_worker_precaches_the_stylesheet_and_app_script(www: Path) -> None:
    """The two assets whose absence turns the app into an unstyled blank page."""
    entries = set(_sw_precache_list(www))
    assert "/style.css" in entries
    assert "/app.js" in entries


def test_service_worker_cache_name_is_versioned(www: Path) -> None:
    """A cache name must change when the assets do, or `activate` never evicts."""
    source = (www / "sw.js").read_text()
    match = re.search(r'var\s+CACHE\s*=\s*"([^"]+)"', source)
    assert match, 'sw.js no longer declares a `var CACHE = "..."` name'
    assert re.search(r"-v\d+$", match.group(1)), (
        f"cache name {match.group(1)!r} has no -vN suffix; the activate handler "
        "deletes every cache whose name differs from CACHE, so an unversioned "
        "name means stale assets survive a deploy forever"
    )


def test_index_html_references_resolve(www: Path) -> None:
    missing = [
        ref
        for ref in _index_local_references(www)
        if ref not in VIRTUAL_PATHS and not _resolve(www, ref).is_file()
    ]
    assert not missing, f"index.html references files that do not exist: {missing}"


def test_manifest_is_valid_and_its_icons_exist(www: Path) -> None:
    manifest = json.loads((www / "manifest.json").read_text())
    for field in ("name", "short_name", "start_url", "display", "icons"):
        assert manifest.get(field), f"manifest.json is missing {field!r}"
    missing = [
        icon["src"] for icon in manifest["icons"] if not _resolve(www, icon["src"]).is_file()
    ]
    assert not missing, f"manifest.json lists icons that do not exist: {missing}"


def test_apple_touch_icon_is_present(www: Path) -> None:
    """iOS ignores the manifest for home-screen icons and reads this instead."""
    assert (www / "apple-touch-icon.png").is_file()


def test_committed_devices_json_satisfies_the_app_contract(www: Path) -> None:
    """The committed copy is a placeholder, but it must still be *usable*.

    The release bundle overwrites it from upstream (ADR-001). Local development
    and the service-worker precache both serve this file as-is, so a broken
    committed copy is a real breakage even though it never reaches production.
    """
    validate((www / "devices.json").read_bytes())


def test_devices_json_is_not_referenced_by_index_html(www: Path) -> None:
    """It is fetched at runtime by app.js, never linked as a page asset.

    Pinned because a well-meaning `<link rel=preload>` would make the file a
    hard page dependency and change what a failed upstream fetch costs.
    """
    assert "devices.json" not in "".join(_index_local_references(www))


@pytest.mark.parametrize("filename", ["index.html", "app.js", "style.css", "sw.js"])
def test_source_files_are_non_empty(www: Path, filename: str) -> None:
    assert (www / filename).stat().st_size > 0


def test_validate_rejects_a_light_missing_its_off_command() -> None:
    """The producer-side check upstream would pass this; app.js would not.

    radiofrequency's publish script only asserts ``unit`` and ``commands``, so a
    profile that exports an ``on`` and no ``off`` publishes cleanly and renders
    an Off button that POSTs ``undefined``. This is the gap this repo closes.
    """
    payload = {
        "lights": [{"unit": "window", "label": "Window", "commands": {"on": {"pulses": [[1, 2]]}}}]
    }
    with pytest.raises(FetchError, match="missing the 'off' command"):
        validate(json.dumps(payload).encode())
