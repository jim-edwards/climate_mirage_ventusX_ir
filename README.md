# Mirage VentusX IR Climate — Home Assistant Integration

Home Assistant custom integration for the **Mirage Ventus X Inverter mini-split** (model OVKH241A) and compatible units. Uses the HA 2026.6+ native infrared framework.

---

## Requirements

- Home Assistant **2026.6.0 or later** (native infrared framework required)
- An IR blaster already configured in HA as an **infrared emitter** entity (e.g. an ESPHome node with `remote_transmitter` proxied via the HA infrared integration)
- *(Optional)* An IR receiver configured as an **infrared receiver** entity to track state changes made with the physical remote

---

## Installation via HACS (recommended)

1. Open **HACS** in your HA sidebar.
2. Click the three-dot menu (⋮) in the top-right corner and select **Custom repositories**.
3. Paste the repository URL:
   ```
   https://github.com/jim-edwards/climate_mirage_ventusX_ir
   ```
4. Set **Category** to `Integration` and click **ADD**.
5. Search for **Mirage VentusX IR Climate** in the HACS Integrations tab and click **Download**.
6. Restart Home Assistant.
7. Proceed to [Configuration](#configuration).

---

## Manual Installation

1. Download or clone this repository.
2. Copy the `custom_components/mirage_ventusx` folder into your HA configuration directory:
   ```
   <ha-config>/custom_components/mirage_ventusx/
   ```
3. Restart Home Assistant.
4. Proceed to [Configuration](#configuration).

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Mirage VentusX**.
3. Fill in the setup form:
   - **Device name** — friendly name shown in the UI (e.g. `Bedroom AC`)
   - **Infrared emitter** — select the IR blaster entity that will transmit commands to the unit
   - **Infrared receiver** *(optional)* — select an IR receiver entity; when set, pressing the physical remote will automatically update the HA entity state
4. Click **Submit**. A new climate entity appears under the device.

> **Note:** If this is a fresh install the integration may log `IR receiver not yet available, retrying in 30 s` on first boot while the ESPHome device is still connecting — this is normal and resolves automatically.

---

## Features

| Feature | Support |
|---------|---------|
| HVAC modes | Off, Cool, Heat, Dry, Fan Only, Heat/Cool (Auto) |
| Temperature range | 61–88 °F (16–31 °C), 1 °F steps |
| Fan speeds | Auto, Low, Medium, High |
| Swing | Off, Vertical, Horizontal, Both |
| State restore on restart | ✓ Last state persisted across HA restarts |
| Physical remote tracking | ✓ When infrared receiver is configured |

---

## ESPHome Native Component

A standalone ESPHome climate platform is also included in [`components/mirage_ventusx/`](components/mirage_ventusx/). This builds the Mirage VentusX climate control directly into the ESPHome firmware — no Home Assistant integration or HA infrared framework needed. Use this if you want local control without HA, or if you are building a dedicated IR controller node.

### Adding to your ESPHome configuration

```yaml
external_components:
  - source:
      type: git
      url: https://github.com/jim-edwards/esphome_climate_mirage_ventusX_ir
      ref: main
    components: [mirage_ventusx]

remote_transmitter:
  id: remote_tx
  pin: GPIO3
  carrier_duty_percent: 50%
  non_blocking: true
  rmt_symbols: 48

# Optional — enables physical-remote state tracking
remote_receiver:
  id: remote_rx
  pin:
    number: GPIO4
    inverted: true
    mode:
      input: true
      pullup: true
  tolerance: 25%
  idle: 10ms

climate:
  - platform: mirage_ventusx
    name: "Mirage Ventus X"
    transmitter_id: remote_tx
    receiver_id: remote_rx   # remove this line if you have no receiver
```

### Notes

- `receiver_id` is optional. When omitted the component is transmit-only and assumes default state on boot.
- `non_blocking: true` on the transmitter is strongly recommended on ESP32-C3 — it runs the RMT peripheral via interrupt rather than CPU polling, which prevents WiFi contention from garbling IR pulses.

---

## Protocol Reference

The Mirage VentusX uses **AEHA framing** at 38 kHz with a proprietary 12-byte payload.

- **Address:** `0xC4D3`
- **T (pulse width):** 425 µs
- **Header:** 8T mark / 4T space
- **Bit encoding:** 1T mark + 3T space = `1`, 1T mark + 1T space = `0`
- **Transmission:** wake packet → ~33 ms gap → data packet

### Packet Structure

| Byte | Description |
|------|-------------|
| 0–3  | Header / device identifier |
| 4    | Mode |
| 5    | Temperature |
| 6    | Fan speed + vertical swing |
| 7–9  | Reserved (always `0x00`) |
| 10   | Horizontal swing + flags |
| 11   | Checksum |

### Byte 0 — Device ID
Always `0x64`

### Byte 1 — Packet Type

| Value | Meaning |
|-------|---------|
| `0x80` | Data packet |
| `0x40` | Wake packet |

### Byte 3 — Power / Flags

| Bit | Meaning |
|-----|---------|
| `0x20` | Power on |
| `0x04` | Always set |

### Byte 4 — HVAC Mode (upper nibble)

| Mode | Value |
|------|-------|
| Cool | `0xC0` |
| Heat | `0x80` |
| Dry  | `0x40` |
| Fan  | `0xE0` |
| Auto | `0x10` |

### Byte 5 — Temperature

Range: 61–88 °F. The upper nibble is a lookup index; odd °F values set bit `0x20` in byte 10.

| Nibble index | °F (even) | Nibble index | °F (even) |
|:---:|:---:|:---:|:---:|
| 0 | 88 | 8 | 86 |
| 1 | 73 | 9 | 72 |
| 2 | 81 | 10 | 79 |
| 3 | 66 | 11 | 64 |
| 4 | 84 | 12 | 82 |
| 5 | 70 | 13 | 68 |
| 6 | 77 | 14 | 75 |
| 7 | 63 | 15 | 61 |

### Byte 6 — Fan Speed + Vertical Swing

Fan speed occupies the upper 3 bits (`0xE0` mask); vertical swing uses bits `0x1C`.

| Fan | Value | Swing | Value |
|-----|-------|-------|-------|
| Auto | `0x00` | Off | `0x00` |
| Low / Mute | `0x40` | On | `0x1C` |
| Medium | `0xC0` | | |
| High | `0xA0` | | |

### Byte 10 — Flags

| Bit | Meaning |
|-----|---------|
| `0x10` | Horizontal swing on |
| `0x20` | Temperature is odd °F |
| `0x01` | Always set |

### Byte 11 — Checksum

```
s        = sum(bit_reverse(d[i]) for i in 0..10)
checksum = bit_reverse((s - 0x12) & 0xFF)
```

Where `bit_reverse` mirrors all 8 bits of a byte.
