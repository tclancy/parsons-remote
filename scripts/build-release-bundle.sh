#!/usr/bin/env bash
# Build (and optionally publish) the parsons-remote release bundle.
#
# Local:   TAG=v0.1.0 scripts/build-release-bundle.sh
# Publish: TAG=v0.1.0 scripts/build-release-bundle.sh --publish
# CI:      TAG="$GITHUB_REF_NAME" scripts/build-release-bundle.sh --publish
#
# When TAG is unset locally, falls back to the exact tag pointing at HEAD.
#
# Produces, under dist/:
#   parsons-remote-<TAG>.tar.gz         a single top-level www/ directory
#   parsons-remote-<TAG>.tar.gz.sha256  checksum, in `shasum -c` format
#
# The homelab `products` role consumes both (tclancy/homelab#269): it downloads
# the tarball, verifies the checksum against a value pinned in
# group_vars/homelab/vars.yml, unpacks to
# ~/sources/parsons-remote-releases/<TAG>/ and symlinks `current` at it.
#
# devices.json is fetched from the newest radiofrequency release and REPLACES
# the copy committed under www/. If that fetch fails, so does this script —
# shipping the committed copy would be exactly the cross-repo drift the
# extraction exists to remove (docs/decisions/001-...).
#
# --publish is idempotent for a given tag: it creates the release if missing and
# clobbers the assets if they are already there.

set -euo pipefail

PUBLISH=0
if [[ "${1:-}" == "--publish" ]]; then
    PUBLISH=1
elif [[ -n "${1:-}" ]]; then
    # No ${1@Q} here — that is bash 4.4+, and /bin/bash on macOS is 3.2.
    echo "ERROR: unknown argument '${1}' (expected --publish or nothing)" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TAG="${TAG:-}"
if [[ -z "$TAG" ]]; then
    TAG="$(git describe --tags --exact-match HEAD 2>/dev/null || true)"
fi
if [[ -z "$TAG" ]]; then
    echo "ERROR: TAG env var not set and HEAD has no exact tag." >&2
    echo "Usage: TAG=vX.Y.Z $0 [--publish]" >&2
    exit 2
fi

BUNDLE="parsons-remote-${TAG}.tar.gz"
STAGE="dist/stage"

# Clean the staging tree on any exit, so an aborted build (e.g. the upstream
# fetch failing) does not leave a half-populated www/ around to confuse the
# next run or a human poking at dist/.
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

echo "==> Building $BUNDLE"

echo "==> Running asset-integrity fence"
# `not integration` excludes tests/test_release_bundle.py, which invokes THIS
# script — without the deselect the fence would recurse. --no-cov and
# -p no:cacheprovider keep the inner run from racing an outer one on .coverage.
uv run pytest -q --no-cov -p no:cacheprovider -m "not integration"

echo "==> Staging www/"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R www "$STAGE/www"

echo "==> Fetching devices.json from the radiofrequency release"
# No fall-back on failure: set -e propagates, and the committed copy staged
# above is left un-overwritten only in the case where we abort anyway.
uv run python scripts/fetch_devices_json.py --repo "${UPSTREAM_REPO:-tclancy/radiofrequency}" \
    -o "$STAGE/www/devices.json"

echo "==> Packing"
# COPYFILE_DISABLE stops macOS tar writing ._ AppleDouble sidecars into the
# archive, which would then unpack onto the homelab as junk next to every file.
COPYFILE_DISABLE=1 tar -czf "dist/${BUNDLE}" -C "$STAGE" www
# $STAGE is removed by the EXIT trap.

echo "==> Checksumming"
(cd dist && shasum -a 256 "$BUNDLE" > "${BUNDLE}.sha256")
cat "dist/${BUNDLE}.sha256"

if [[ "$PUBLISH" -eq 1 ]]; then
    echo "==> Creating release (idempotent) and uploading assets"
    # `gh release view || gh release create` rather than `create || true`: the
    # bare `|| true` is idempotent but also swallows a missing contents:write
    # permission, an auth failure, or a nonexistent tag, leaving the operator to
    # diagnose from a confusing `upload` error instead of the real cause.
    gh release view "$TAG" >/dev/null 2>&1 ||
        gh release create "$TAG" --generate-notes --title "$TAG"
    gh release upload "$TAG" "dist/${BUNDLE}" "dist/${BUNDLE}.sha256" --clobber
fi

echo "==> Done."
