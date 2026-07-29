# parsons-remote

Static PWA for controlling LAN devices at 22 Parsons — ceiling fans over the
NodeMCU fan controller, and RF lamps over the 433 MHz transmitter. Add to home
screen on an iPhone and it behaves like a native app.

Extracted from the homelab repo (`services/parsons-remote/www/`) so the PWA
versions independently of the infrastructure that deploys it. See
[tclancy/homelab#256](https://github.com/tclancy/homelab/issues/256).

- **Vocabulary**: [`GLOSSARY.md`](GLOSSARY.md) — canonical names for domain terms.
- **Decisions**: [`docs/decisions/`](docs/decisions/) — ADRs for load-bearing choices.

## Architecture

- No build step for the app itself — plain HTML, CSS, vanilla JS in `www/`.
- `www/devices.json` is **generated**, never hand-edited. It is produced by
  `radiofrequency/scripts/export_web_devices.py` and published as a GitHub
  Release asset by that repo. The release bundle here fetches it — see
  [ADR-001](docs/decisions/001-devices-json-from-upstream-release.md).
- Deployed by the homelab `products` Ansible role, which serves `www/` behind
  Caddy and reverse-proxies `/api/fan/*` and `/api/transmit` to the controllers.

## Layout

| Path | What |
|------|------|
| `www/` | The PWA — served as-is by Caddy. |
| `scripts/fetch_devices_json.py` | Downloads `devices.json` from the newest radiofrequency release. |
| `scripts/build-release-bundle.sh` | Assembles `dist/parsons-remote-<tag>.tar.gz` + `.sha256`. |
| `tests/` | Asset-integrity checks — run in CI and by the release build. |

## Releasing

Tag with a **`v` prefix** and push. `.github/workflows/release.yml` fires on
`v*`, runs the asset tests, fetches the upstream `devices.json`, builds the
tarball, and uploads it plus its `SHA256` checksum to the release.

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The homelab role consumes
`https://github.com/tclancy/parsons-remote/releases/download/<tag>/parsons-remote-<tag>.tar.gz`
and pins the checksum in `group_vars/homelab/vars.yml` — see
[homelab#269](https://github.com/tclancy/homelab/issues/269).

> **That URL needs auth as things stand.** This repo is **private**, so an
> anonymous `GET` of a release asset returns `404` — verified 2026-07-29. A bare
> Ansible `get_url` on the homelab will fail at deploy time, not at PR time.
> Two ways out, and it is Tom's call which: make this repo public (it is a
> ceiling-fan remote with no secrets in it, and `radiofrequency` upstream is
> already public), or have the homelab role send
> `Authorization: token {{ vault_github_release_pat }}` from the Ansible vault —
> or use `gh release download`, which handles auth itself.

To reproduce a bundle locally:

```bash
TAG=v0.1.0 scripts/build-release-bundle.sh
```

## Local development

```bash
uv sync                       # test deps only; the PWA itself needs nothing
uv run pytest                 # asset-integrity checks
python3 -m http.server -d www 8094
```

`/api/*` calls will fail against `http.server` — that path only exists behind
the homelab Caddy config. The UI degrades to an error toast, which is itself
worth eyeballing.

## Agent's Understanding

*Written 2026-07-29 ET by agent:opus for
[parsons-remote#1](https://github.com/tclancy/parsons-remote/issues/1) before
any code, per `agent.md`.*

### The task

This is **PR 2** of the three-PR extraction chain in
[homelab#256](https://github.com/tclancy/homelab/issues/256). Tom created this
repo bare on 2026-07-28. My job: scaffold it to fleet standard, move the PWA
source across from homelab byte-for-byte, and wire the release plumbing that
[homelab#269](https://github.com/tclancy/homelab/issues/269) (PR 3) will consume.

Order of work:

1. Init checklist — `.gitignore`, pre-commit, pytest, radon gate, CI with
   SHA-pinned Actions, `claude-code-review.yml`, Dependabot, GLOSSARY + ADR seeds.
2. Move `www/` and the service README across from homelab `origin/main`.
3. `scripts/fetch_devices_json.py` + `scripts/build-release-bundle.sh`.
4. `release.yml` on `v*`, mirroring radiofrequency's.
5. Asset-integrity tests so CI has something real to run.

### Assumptions

- **The release artifact is a gzipped tarball of `www/`, named
  `parsons-remote-<tag>.tar.gz`, with a sibling `.sha256`.**
  **Why:** homelab#269 states that filename and download URL verbatim and says
  it will verify a SHA256 pinned in `vars.yml`. PR 3 is the only consumer, so
  its stated contract is the requirement — inventing a different shape here
  would just mean rewriting PR 3.

- **The tarball unpacks to a `www/` directory, not to a bare file list.**
  **Why:** homelab#269 unpacks to `~/sources/parsons-remote-releases/<version>/`
  and symlinks `current` at it. A single top-level directory makes the unpack
  idempotent and keeps `tar` from scattering files if the target isn't empty.

- **This repo needs Python only for its tests and build scripts.**
  **Why:** the PWA has no build step and shouldn't grow one. But the fleet CI
  standard is uv + ruff + pytest, and there are real invariants worth pinning
  (see below), so Python earns its place as tooling rather than as runtime.

- **`www/devices.json` stays committed even though it is generated.**
  **Why:** the issue's definition of done requires `www/` be byte-identical to
  homelab `origin/main`, and dropping the file would break `python3 -m
  http.server` local dev and the service-worker precache list. The release build
  overwrites it, so the committed copy never reaches production — see ADR-001
  for how that is enforced rather than hoped for.

### Key decisions

- **The release build fetches `devices.json` and *fails* if it can't, rather
  than falling back to the committed copy.**
  **Why:** a silent fallback reintroduces exactly the cross-repo hand-copy drift
  that #256 exists to kill — the bundle would look fine and ship stale RF pulse
  timings. A failed release is loud and cheap; a silently stale one is neither.
  **Alternatives:** fall back with a warning (rejected — warnings in CI logs are
  not read); drop the committed copy entirely (rejected — breaks local dev and
  the DoD's byte-identical requirement). Recorded as
  [ADR-001](docs/decisions/001-devices-json-from-upstream-release.md).

- **Asset-integrity tests assert the service worker's precache list against the
  filesystem.**
  **Why:** `sw.js` hardcodes `ASSETS = ["/", "/style.css", ...]`. `cache.addAll`
  rejects atomically if *any* entry 404s, so one renamed file silently disables
  offline mode for every installed client — a failure invisible to a browser
  smoke test on a warm cache. This is the one bug class that a static-site repo
  can genuinely regress, so it gets a test.

### Open questions, answered rather than blocked on

**1. Can the first release be cut tonight?** No. radiofrequency's only tag is
`0.1.0` and its `release.yml` triggers on `tags: ['v*']`, so the workflow never
fired and `GET /repos/tclancy/radiofrequency/releases` returns `[]`. There is
nothing upstream to fetch. Steps 1/2/4/5 are complete; step 3 is wired and
unit-tested against a fake transport, but its live path is untested until
`git tag v0.1.0 7fde346d && git push origin v0.1.0` runs on radiofrequency.
**I have deliberately not tagged this repo** — tagging now would fire
`release.yml` into a guaranteed failure and leave a broken v0.1.0 release in
the way of the real one.

**2. Is that the only thing standing between here and homelab#269?** No, and
this one was not in the issue. homelab#269 will `get_url` the release asset
from `https://github.com/tclancy/parsons-remote/releases/download/...`, but
**this repo is private, so that URL 404s anonymously** (checked with `curl`,
2026-07-29). It is a deploy-time failure on the homelab, invisible at PR-review
time, and it lands on PR 3 rather than here. Options are in the Releasing
section above; the cheapest is making this repo public, since it holds a
ceiling-fan remote and its upstream `radiofrequency` is already public.
**Flagged rather than decided — repo visibility is Tom's call, not an agent's.**
