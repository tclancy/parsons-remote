"""Tests for the upstream ``devices.json`` fetch.

The network I/O is injected (``get_json`` / ``get_bytes``) so these exercise the
real parsing, asset lookup and validation code rather than mocking it away. The
last test proves the injection is actually load-bearing: a default-argument
fall-back that silently reaches the network would make every other test here a
no-op against a fake.
"""

import json
import urllib.error
from collections.abc import Callable

import pytest
from fetch_devices_json import (
    ASSET_NAME,
    FetchError,
    asset_url,
    fetch_devices_json,
    latest_release,
    validate,
)

GOOD_PAYLOAD = {
    "lights": [
        {
            "unit": "window",
            "label": "Window",
            "position": 2,
            "commands": {
                "on": {"pulses": [[184, 548]], "repeat_count": 15},
                "off": {"pulses": [[548, 184]], "repeat_count": 15},
            },
        }
    ]
}


def _release(tag: str = "v0.1.0", assets: list[dict] | None = None) -> dict:
    if assets is None:
        assets = [{"name": ASSET_NAME, "url": "https://api.example/assets/1"}]
    return {"tag_name": tag, "assets": assets}


def _json_transport(payload: object) -> Callable[[str], object]:
    return lambda _url: payload


def _http_error(code: int) -> Callable[[str], object]:
    def raise_it(url: str) -> object:
        raise urllib.error.HTTPError(url, code, "boom", {}, None)  # type: ignore[arg-type]

    return raise_it


# --- latest_release -------------------------------------------------------


def test_latest_release_returns_the_payload() -> None:
    assert latest_release("o/r", _json_transport(_release()))["tag_name"] == "v0.1.0"


def test_no_releases_names_the_v_prefix_fix() -> None:
    """This is radiofrequency's exact state today, so the message has to be usable."""
    with pytest.raises(FetchError) as exc:
        latest_release("tclancy/radiofrequency", _http_error(404))
    assert "git tag v0.1.0" in str(exc.value)
    assert "'v*'" in str(exc.value)


def test_other_http_errors_are_reported_with_their_code() -> None:
    with pytest.raises(FetchError, match="GitHub API error 500"):
        latest_release("o/r", _http_error(500))


def test_non_object_payload_is_rejected() -> None:
    with pytest.raises(FetchError, match="Unexpected releases payload"):
        latest_release("o/r", _json_transport([1, 2, 3]))


# --- asset_url ------------------------------------------------------------


def test_asset_url_finds_the_named_asset() -> None:
    assert asset_url(_release(), ASSET_NAME) == "https://api.example/assets/1"


def test_missing_asset_lists_what_was_actually_there() -> None:
    release = _release(assets=[{"name": "firmware.bin", "url": "u"}])
    with pytest.raises(FetchError) as exc:
        asset_url(release, ASSET_NAME)
    assert "firmware.bin" in str(exc.value)


def test_release_with_no_assets_at_all() -> None:
    with pytest.raises(FetchError, match=r"Present: \(none\)"):
        asset_url(_release(assets=[]), ASSET_NAME)


def test_asset_present_but_with_no_download_url() -> None:
    """A named-but-URL-less asset must not fall through to a `None` download."""
    release = _release(assets=[{"name": ASSET_NAME}])
    with pytest.raises(FetchError, match="has no URL"):
        asset_url(release, ASSET_NAME)


# --- validate -------------------------------------------------------------


def test_validate_accepts_a_well_formed_payload() -> None:
    assert validate(json.dumps(GOOD_PAYLOAD).encode())["lights"][0]["unit"] == "window"


def test_validate_rejects_non_json() -> None:
    with pytest.raises(FetchError, match="not valid JSON"):
        validate(b"<html>404</html>")


def test_validate_rejects_a_json_array() -> None:
    with pytest.raises(FetchError, match="must be an object"):
        validate(b"[]")


def test_validate_rejects_an_empty_lights_list() -> None:
    with pytest.raises(FetchError, match="no lights"):
        validate(b'{"lights": []}')


@pytest.mark.parametrize("field", ["unit", "label"])
def test_validate_rejects_a_light_missing_an_identifying_field(field: str) -> None:
    payload = json.loads(json.dumps(GOOD_PAYLOAD))
    del payload["lights"][0][field]
    with pytest.raises(FetchError, match=f"missing '{field}'"):
        validate(json.dumps(payload).encode())


@pytest.mark.parametrize("command", ["on", "off"])
def test_validate_rejects_a_light_missing_a_command(command: str) -> None:
    payload = json.loads(json.dumps(GOOD_PAYLOAD))
    del payload["lights"][0]["commands"][command]
    with pytest.raises(FetchError, match=f"missing the '{command}' command"):
        validate(json.dumps(payload).encode())


def test_validate_rejects_a_light_that_is_not_an_object() -> None:
    with pytest.raises(FetchError, match=r"lights\[0\] is not an object"):
        validate(b'{"lights": ["window"]}')


@pytest.mark.parametrize("empty", [{}, {"repeat_count": 15}, {"pulses": []}, "on"])
def test_validate_rejects_a_command_with_no_pulses(empty: object) -> None:
    """`pulses` is the entire transmit payload; without it the POST is a no-op."""
    payload = json.loads(json.dumps(GOOD_PAYLOAD))
    payload["lights"][0]["commands"]["off"] = empty
    # An empty dict is falsy and trips the earlier "missing" branch; the other
    # three reach the pulses check. Both are rejections, which is the contract.
    with pytest.raises(
        FetchError, match=r"(missing the 'off' command|'off' command has no pulses)"
    ):
        validate(json.dumps(payload).encode())


def test_validate_rejects_commands_that_are_not_an_object() -> None:
    payload = json.loads(json.dumps(GOOD_PAYLOAD))
    payload["lights"][0]["commands"] = ["on", "off"]
    with pytest.raises(FetchError, match="no commands object"):
        validate(json.dumps(payload).encode())


# --- fetch_devices_json ---------------------------------------------------


def test_fetch_returns_bytes_and_tag() -> None:
    raw = json.dumps(GOOD_PAYLOAD).encode()
    got, tag = fetch_devices_json(
        "o/r", get_json=_json_transport(_release("v1.2.3")), get_bytes=lambda _u: raw
    )
    assert got == raw
    assert tag == "v1.2.3"


def test_fetch_validates_before_returning() -> None:
    """A 200 that returns a login page must not become a released bundle."""
    with pytest.raises(FetchError, match="not valid JSON"):
        fetch_devices_json(
            "o/r", get_json=_json_transport(_release()), get_bytes=lambda _u: b"<html>"
        )


def test_fetch_reports_a_failed_asset_download() -> None:
    with pytest.raises(FetchError, match="HTTP 403"):
        fetch_devices_json("o/r", get_json=_json_transport(_release()), get_bytes=_http_error(403))


def test_injection_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the fakes are actually used — break the real transport and re-run.

    Without this, a refactor that ignored the injected callables would leave
    every test above passing while silently hitting the network in CI.
    """

    def explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("real network transport was used")

    monkeypatch.setattr("fetch_devices_json._urlopen_json", explode)
    monkeypatch.setattr("fetch_devices_json._urlopen_bytes", explode)

    raw = json.dumps(GOOD_PAYLOAD).encode()
    got, _tag = fetch_devices_json(
        "o/r", get_json=_json_transport(_release()), get_bytes=lambda _u: raw
    )
    assert got == raw

    with pytest.raises(AssertionError, match="real network transport"):
        fetch_devices_json("o/r")
