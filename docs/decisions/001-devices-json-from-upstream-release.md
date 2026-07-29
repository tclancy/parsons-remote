# ADR-001: devices-json-from-upstream-release

**Status:** accepted
**Date:** 2026-07-29
**Deciders:** tclancy (shape chosen on tclancy/homelab#256), agent:opus (mechanism)

## Context

`devices.json` holds the RF pulse timings for the lamps. It is *generated* by
`radiofrequency/scripts/export_web_devices.py` from the YAML profiles that repo
owns, and until now it reached the PWA by hand-copy into the homelab tree. That
cross-repo hand-copy is the drift trap named in
[homelab#256](https://github.com/tclancy/homelab/issues/256), and Tom's answer
there was explicit: *"the YAML profiles in radiofrequency stay the single source
of truth and the copy step gets automated."* Extracting the PWA into this repo
(homelab#256 → [parsons-remote#1](https://github.com/tclancy/parsons-remote/issues/1))
is the moment that automation has to be built, because it decides what a release
bundle contains.

The tension: the file must be present for local development and for the service
worker's precache list, but the *committed* copy must never reach production —
otherwise the drift just moves from homelab into this repo.

## Decision

The committed `www/devices.json` is a **placeholder** with exactly one job:
keeping `python3 -m http.server -d www` and the `sw.js` precache list working.
`scripts/build-release-bundle.sh` stages `www/`, then **overwrites**
`devices.json` from the newest `tclancy/radiofrequency` release before packing
the tarball. If that fetch fails for any reason — no release, no asset, bad
JSON, or a payload that does not satisfy the shape `app.js` dereferences — the
build **exits non-zero and no release is published**. There is no fall-back to
the committed copy and no `--allow-stale` escape hatch.

## Consequences

- **Enables:** the release bundle is provably derived from upstream's YAML at
  build time, so a lamp added in radiofrequency reaches the phone by cutting a
  tag here rather than by remembering to copy a file.
- **Blocks / makes harder:** this repo cannot cut a release at all until
  radiofrequency publishes one. As of 2026-07-29 it has not — its only tag is
  `0.1.0`, its `release.yml` triggers on `tags: ['v*']`, so the workflow has
  never fired and `GET /repos/tclancy/radiofrequency/releases` returns `[]`.
  The fix is upstream and is one command: `git tag v0.1.0 7fde346d && git push
  origin v0.1.0`. Deliberately chosen over an escape hatch — a hard block is
  visible and gets fixed; a bypass flag becomes the default path within a month.
- **Reverses if:** radiofrequency stops publishing releases and the generation
  moves in here (e.g. this repo grows a dependency on the exporter). Then the
  committed copy becomes a build *output* rather than a placeholder and this ADR
  is superseded.

## Alternatives considered

- **Fall back to the committed copy with a warning.** Rejected: nobody reads
  green-build warnings. The bundle would look healthy and ship stale pulse
  timings — the exact failure #256 exists to remove, relocated one repo over.
- **Drop `www/devices.json` from the repo entirely.** Rejected: it breaks
  `python3 -m http.server` local dev, breaks the `sw.js` precache list (which
  `cache.addAll` rejects atomically), and breaks parsons-remote#1's definition
  of done, which requires `www/` be byte-identical to homelab `origin/main`.
- **Have radiofrequency push the file into this repo on release.** Rejected:
  inverts the dependency so the producer needs write credentials on the
  consumer, and leaves a generated file mutating on `main` between tags.
- **Vendor the exporter and generate here.** Rejected: duplicates the YAML
  profiles or adds a cross-repo source dependency, which is the thing #256 is
  removing.
