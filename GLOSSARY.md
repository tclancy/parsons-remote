# Glossary

<!--
Canonical vocabulary for this project — the single source of truth for what
each domain term means and what to call it.

Discipline:
  1. Before naming any new domain concept (variable, class, PR title, issue
     title, prose in a README), search this file for the term.
  2. If it exists, use it verbatim in code and prose.
  3. If it doesn't and your work introduces it, add a one-line row in the
     same PR.
  4. Aliases-to-avoid ride on the row that owns the canonical name so an
     agent hitting a legacy name lands here and switches over.

Not documentation — this captures what is currently *live in the repo*, not
everything that could be. When a term drops out of the codebase, drop it
from the glossary in the PR that removes it.
-->

## Terms

<!-- Alphabetical by canonical name. One line per term. -->

- **command** — A named action on a device: `light`/`speed1`…`speed3`/`off` for a fan, `on`/`off` for a lamp. In `devices.json` a lamp command is an object of `pulses` + `repeat_count`; in `app.js` a fan command is a URL path segment.
- **device** — Anything the PWA can control. Two kinds today, and they do not share a transport: fans (hardcoded in `app.js`, driven by `GET /api/fan/{id}/{cmd}`) and lamps (loaded from `devices.json`, driven by `POST /api/transmit`).
- **devices.json** — The generated lamp definitions. Produced by `radiofrequency/scripts/export_web_devices.py`, published as a release asset there, and fetched into the release bundle here. **Never hand-edited.** (aka: light definitions, RF bundle)
- **fan controller** — The NodeMCU on the LAN that Caddy reverse-proxies `/api/fan/*` to. Distinct from the *lamp transmitter*.
- **lamp** — A 433 MHz RF-switched light. Called `light` in `devices.json` and in `app.js`'s DOM code (`buildLightsCard`, `sendLight`); `lamp` is the prose form. (aka: light)
- **lamp transmitter** — The 433 MHz transmitter behind `POST /api/transmit`. Single-threaded: it busy-waits during a send, so "All On/Off" must serialize its four requests.
- **precache list** — The `ASSETS` array in `www/sw.js`. `cache.addAll` rejects atomically, so one missing entry disables offline mode entirely; pinned by `tests/test_pwa_assets.py`.
- **release bundle** — `parsons-remote-<tag>.tar.gz`, a gzipped tarball with a single top-level `www/` directory, plus a sibling `.sha256`. The unit homelab deploys. (aka: artifact, tarball)
- **unit** — The stable identifier for a lamp in `devices.json` (`window`, `couch`, `speaker`, `chairs`). Distinct from `label`, which is the display caption, and from `position`, which is the physical remote-button slot.
- **upstream** — `tclancy/radiofrequency`, the repo that owns the RF profiles and generates `devices.json`. Never this repo's `origin`.
- **www/** — The PWA source, served verbatim by Caddy with no build step. The whole contents of a release bundle.

## Related decisions

Load-bearing terminology choices go in `docs/decisions/` as ADRs. Link them
here when a term's meaning is contested or has a non-obvious rationale:

- **devices.json** — see [ADR-001](docs/decisions/001-devices-json-from-upstream-release.md)
  for why the committed copy is a placeholder that the release build must
  overwrite, and why a fetch failure fails the release instead of falling back.
