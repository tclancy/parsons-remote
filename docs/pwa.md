# 22 Parsons Remote

*Moved verbatim from `homelab:services/parsons-remote/README.md` as part of the
extraction ([homelab#256](https://github.com/tclancy/homelab/issues/256)). Paths
under `ansible/` refer to the **homelab** repo, which still owns deployment;
everything under `www/` now lives here.*

Static web app for controlling LAN devices at 22 Parsons. Designed as a PWA — add to home screen on an iPhone and it feels like a native app.

## Architecture

- **Caddy** serves the static site and reverse-proxies `/api/fan/*` requests to the NodeMCU fan controller on the LAN
- No build step — plain HTML, CSS, vanilla JS
- Deployed via Ansible like all other homelab services

## Adding a New Device

Edit `www/app.js`. The `DEVICES` array defines all controllable devices:

```js
var DEVICES = [
  {
    id: 1,                    // used in the API path: /api/fan/{id}/{cmd}
    name: "Living Room Fan",  // display label on the card
    commands: [
      { label: "☀", cmd: "light", style: "btn-light" },
      { label: "1", cmd: "speed1", style: "btn-speed" },
      { label: "2", cmd: "speed2", style: "btn-speed" },
      { label: "3", cmd: "speed3", style: "btn-speed" },
      { label: "Off", cmd: "off", style: "btn-off" },
    ],
  },
  // add more devices here
];
```

Each command maps to a GET request: `GET /api/fan/{id}/{cmd}`, which Caddy proxies to `http://{fan_controller_host}/fan/{id}/{cmd}`.

### Button styles

| Style | Use for |
|-------|---------|
| `btn-light` | Light/toggle buttons (amber highlight) |
| `btn-speed` | Speed or level settings (blue) |
| `btn-off` | Power off (red) |

### For non-fan devices

If you add a device type that uses different API paths (e.g., a garage door), you'll need to:

1. Add a new `handle` block in the Caddyfile template (`ansible/roles/products/templates/parsons-remote-Caddyfile.j2`)
2. Update the JS to build the correct fetch URL for the new device type

## Deployment

```bash
# Deploy or update the service
itguy deploy parsons-remote

# Or via Ansible directly
ansible-playbook ansible/playbook.yml --tags parsons-remote
```

The service runs at `http://homelab.local:8094`.

## Configuration

In `ansible/group_vars/homelab/vars.yml`:

- `fan_controller_host` — hostname or IP of the NodeMCU fan controller (default: `ceilingfans.local`)
- `service_ports.parsons_remote` — port the web app listens on (default: `8094`)

The Caddy container runs with `network_mode: host` so it can resolve `ceilingfans.local` via mDNS (same approach as Home Assistant). If mDNS is unreliable, set `fan_controller_host` to the NodeMCU's static IP address instead.
