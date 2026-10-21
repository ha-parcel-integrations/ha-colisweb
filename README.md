# Colisweb Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-colisweb.svg)](https://github.com/ha-parcel-integrations/ha-colisweb/releases)
[![Downloads](https://img.shields.io/github/downloads/ha-parcel-integrations/ha-colisweb/total.svg)](https://github.com/ha-parcel-integrations/ha-colisweb/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 📦 Part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/), a family of package-tracking integrations for Home Assistant that all publish the same parcel format, statuses and events, so they plug into cross-carrier automations and the optional [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator). Browse the other carriers on the website.
>
> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Colisweb](https://www.colisweb.com) deliveries (France). Colisweb arranges home delivery of bulky goods for retailers, so a delivery is an appointment with a time slot and a few milestones rather than a scan-by-scan parcel journey. No account is needed — you enter the tracking number yourself, just like on the Colisweb website.

> **Pre-release.** Only one Colisweb step has been seen on a real delivery so far; the other steps are mapped from the carrier's published vocabulary and unverified. Anything unrecognised is logged once as a warning with a link to report it.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Colisweb deliveries by tracking number — no account needed
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / …), the carrier's own step, the delivery slot (until the parcel is delivered) and a tracking link
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar with the expected delivery windows
- `colisweb.track_parcel` / `colisweb.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel history of the delivery milestones
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2025.12 or newer
- A Colisweb delivery and its tracking number: 8 to 32 digits, sent by SMS or
  e-mail in the delivery notifications — no account needed

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-colisweb` as an **Integration**.
3. Install **Colisweb** and restart Home Assistant if HACS asks you to.

Or click the button below to open it directly in HACS:

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ha-parcel-integrations&repository=ha-colisweb&category=integration)

### Manual

Copy `custom_components/colisweb` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=colisweb)

Or set it up by hand: add the integration via **Settings → Devices & Services → Add Integration → Colisweb**. There is nothing to fill in: the hub is created immediately (Colisweb tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`colisweb.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking number is in the SMS or e-mail Colisweb sent about the delivery. A number is only checked for its shape (8 to 32 digits, spaces and dashes removed) when you add it; it is not looked up first, because Colisweb answers the same empty error for an unknown number and for a temporary outage.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking numbers. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with the delivery milestones (confirmed, picked up, delivered). |

Polling isn't one of these settings: the integration polls on a dynamic,
status-driven schedule with nothing to configure.

## Dynamic polling

Polling isn't a setting here — the integration adjusts its own cadence to
what your tracked parcels are actually doing:

- **Quiet hours** — no polling between 00:00–06:00 local time, aside from one
  catch-up check at each end of that window (around midnight and around 6
  AM), so an overnight update is never missed.
- **Hot (every 15 minutes)** — while any tracked parcel is out for delivery
  today, starting an hour before its delivery window opens (or immediately if
  no window is known yet).
- **Normal (every 45 minutes)** — for anything else still on its way.
- **Fully paused** — once every tracked parcel has been delivered, or nothing
  is tracked at all, polling stops until you add a parcel back (adding one
  always triggers an immediate check, regardless of the pause).
- A small, fixed per-hub offset is added on top, so not every Colisweb
  hub out there polls at exactly the same second.

Colisweb publishes a delivery slot rather than a live ETA. While a delivery is out for delivery without a slot (or with one that was rescheduled), it stays in the hot tier.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Colisweb → ⋮ → Delete**. Nothing is stored on Colisweb's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.colisweb_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.colisweb_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.colisweb_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.colisweb_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.colisweb_last_successful_update` | Diagnostic: when Colisweb was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `registered` | The delivery is confirmed or scheduled |
| `in_transit` | The goods were picked up |
| `out_for_delivery` | The delivery is under way |
| `delivered` | Delivered |
| `returning` | Going back to the sender |
| `problem` | Colisweb reports a failed, cancelled or non-deliverable delivery |
| `unknown` | Not looked up yet, or a step we have not mapped yet |

Colisweb has no pickup-point step, so `at_pickup_point` never occurs. The carrier's own step name is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Colisweb device):

| Event | When |
|---|---|
| `colisweb_parcel_registered` | A new parcel appears in the active list |
| `colisweb_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `colisweb_parcel_delivered` | A parcel is delivered |
| `colisweb_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `colisweb.track_parcel` | `tracking_code` | Start tracking a parcel |
| `colisweb.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.colisweb: debug
```

## Troubleshooting

- **A number is refused when adding it** — it has to be 8 to 32 digits. Spaces and dashes are removed for you; any other character is refused, so copy the number from the SMS or e-mail.
- **A new number shows as `unknown`** — Colisweb answers an unknown number and a temporary outage with the same empty error, so the parcel stays `unknown` and is retried on the normal schedule until Colisweb knows it. One warning is logged per number.
- **A parcel keeps its old state** — a failed lookup never changes the last good state; the integration just retries on the normal schedule.
- **A step logs "Unrecognised Colisweb status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-colisweb/issues/new?template=unrecognised_status.yml) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://ha-parcel-integrations.github.io/) for the current list of supported carriers.

## Disclaimer

This is an independent, community-built project. It is not affiliated with, endorsed by, sponsored by, or supported by Colisweb, Home Assistant, or any other third party referenced in this project. Please don't contact Colisweb for support with this integration.

All third-party trademarks, trade names, product names, logos, and other brand assets are the property of their respective owners. References to them are solely to identify the relevant carrier or service and do not imply affiliation, sponsorship, or endorsement. Nothing in this project grants or implies any licence or right to use third-party brand assets.

This integration relies on a public, unofficial, undocumented Colisweb interface that needs no account or key. These may change or be withdrawn without notice and may be subject to Colisweb's terms. Data is sent only to Colisweb's own services or those of its group; this project operates no servers of its own. You are responsible for ensuring that your use complies with applicable law and those terms. Use is at your own risk; see the [licence](LICENSE) for warranty limitations.

It uses the same public tracking lookup as the Colisweb consumer website, one number at a time, and only for numbers you enter yourself.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
