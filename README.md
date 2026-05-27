# Intelbras DVR

[🇧🇷 Português](README.pt-BR.md)

Custom Home Assistant integration for **Intelbras / Dahua** DVRs, featuring:

- 🎥 Cameras via HTTP snapshot (digest auth) + RTSP stream — one entity per channel.
- 🔧 In-UI reauthentication: `intelbras_dvr.apply_credentials` service to update
  host / username / password without recreating the integration.
- 🌐 **MAC-based IP tracking**: if DHCP gives the DVR a new IP (after a power
  outage or router reboot), the integration detects the original MAC and
  updates the host automatically — no manual intervention.
- 📋 `last_apply_result` sensor reporting the outcome of the latest
  (re)authentication or auto-tracking event.

Inspired by the `generic_camera` pattern but tailored for Intelbras/Dahua DVRs,
including the classic login-lockout problem after several failed login
attempts (the integration applies a local back-off on repeated 401s).

## Installation

### Via HACS (recommended)
1. HACS → menu (⋮) → **Custom repositories**.
2. URL: `https://github.com/Constantini21/intelbras_dvr` (category *Integration*).
3. Install **Intelbras DVR** and restart Home Assistant.
4. Settings → Devices & Services → **Add Integration** → "Intelbras DVR".

### Manual
Copy `custom_components/intelbras_dvr/` into
`<config>/custom_components/intelbras_dvr/` and restart Home Assistant.

## Configuration (config flow)

| Field | Default | Description |
|-------|---------|-------------|
| `host` | — | DVR IP address (e.g. `172.16.0.12`) |
| `username` | `admin` | DVR username |
| `password` | — | DVR password |
| `channels` | `4` | Number of channels to create |
| `rtsp_port` | `554` | RTSP port |
| `track_by_mac` | `true` | Enable automatic IP tracking by MAC |
| `scan_interval` | `300` | Tracking interval in seconds |

On submit, the integration calls
`GET http://<host>/cgi-bin/snapshot.cgi?channel=1` with digest auth. On HTTP
200 it creates `N` camera entities.

## Service `intelbras_dvr.apply_credentials`

```yaml
service: intelbras_dvr.apply_credentials
data:
  entry_id: <config_entry_id>   # optional if there is only one installation
  host: 172.16.0.12
  username: admin
  password: new-password
```

Validates the new credentials against the DVR, updates the config entry, and
reloads the integration in-place (no Home Assistant restart needed).

## MAC-based IP auto-tracking

When enabled:
- Every `scan_interval` (default 300 s) the integration reads the local ARP
  table (`ip neigh`) and finds the MAC associated with the current IP.
- On later cycles, if the MAC's IP changes, the config entry is updated and
  the integration is reloaded automatically.
- Works **only** when Home Assistant runs in `network_mode: host` (or on bare
  metal). Bridged containers can't see the host's ARP table.

## `last_apply_result` sensor

Surfaces the latest service call or auto-tracking outcome
(`OK: ...`, `FAIL: ...`, or `AUTO: ...`).

## Known limitations

- Intelbras/Dahua DVRs lock out the client IP for ~30 min after 3–5 failed
  login attempts. The integration detects HTTP 401 and pauses stream retries
  for 5 min to avoid making the ban worse.
- MAC discovery only works when Home Assistant is on the same L2 as the DVR.

## License

MIT — see [LICENSE](LICENSE) if present, otherwise use freely with attribution.
