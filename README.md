# SIG Health BLE

A **local_push** Home Assistant custom integration for Bluetooth SIG-compliant health devices:

- 🩺 Blood Pressure Monitors (BLE service `0x1810`)
- 🩸 Glucose Meters (BLE service `0x1808`)
- ⚖️ Weight Scales / Body Composition (BLE services `0x181D` / `0x181B`)

All three device types share a single integration entry point, common BLE connection infrastructure, and a unified reconfigure/repair flow for managing bonded ESPHome proxies.

---

## Installation

### HACS (recommended)

1. Add this repo as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/) in HACS.
2. Search **SIG Health BLE** and install.
3. Restart Home Assistant.

### Manual

```bash
cp -r custom_components/sig_health_ble /config/custom_components/sig_health_ble
```

Restart Home Assistant.

---

## Setup

1. **Take a measurement** on your device — BPM monitors, glucose meters, and scales all advertise briefly after a reading.
2. Home Assistant discovers the device automatically and shows a notification. Click **Configure** → select device type → confirm.
3. Alternatively: **Settings → Devices & Services → Add Integration → SIG Health BLE** and enter the MAC address manually.

> **ESPHome Bluetooth Proxy is strongly recommended** for reliable reception, especially for bonded devices. See [ESPHome Bluetooth Proxies](https://esphome.io/projects/?type=bluetooth_proxy).

---

## Compatible Devices

### Blood Pressure Monitors

Any device advertising service `0x1810` with characteristic `0x2A35` should work:

| Brand    | Example models                  |
|----------|---------------------------------|
| A&D      | UA-651BLE, UA-767PBT-C          |
| Omron    | M7 Intelli IT, M4 Intelli       |
| Medisana | BU 575, BU 546                  |
| Beurer   | BM 57, BM 85                    |
| Sanitas  | SBM 67, SBM 70                  |

### Glucose Meters

Any device advertising service `0x1808`:

| Brand        | Example models                  |
|--------------|---------------------------------|
| Contour Next | Contour Next One, Contour Plus  |
| Accu-Chek    | Guide, Instant                  |
| OneTouch     | Verio Reflect, Verio Flex       |
| Beurer       | GL 50 evo, GL 44                |
| iHealth      | Smart Gluco-Monitoring System   |

### Weight Scales

Any device advertising service `0x181D` and/or `0x181B`:

| Brand   | Example models            | Bonding  |
|---------|---------------------------|----------|
| Beurer  | BF 105                    | Optional |
| Beurer  | BF 720                    | Required |
| A&D     | UC-352BLE, UC-450BLE      | No       |
| Omron   | HBF-702T, HBF-222T        | No       |
| Tanita  | RD-953                    | No       |

> **Note:** Many cheap scales use proprietary BLE protocols. This integration only works with devices that use the SIG standard services above. Devices that use proprietary GATT services may need a device-specific parser — open an issue with a Wireshark/nRF Sniffer capture.

---

## Sensors

### Blood Pressure Monitor

| Entity | Unit | Notes |
|--------|------|-------|
| Systolic Pressure | mmHg / kPa | HA converts units automatically |
| Diastolic Pressure | mmHg / kPa | |
| Mean Arterial Pressure | mmHg / kPa | |
| Pulse Rate | bpm | If reported by device |
| Last Measurement Time | — | Device timestamp if available |
| User ID | — | Multi-user devices |
| Body Movement Detected | — | Measurement status flag |
| Irregular Pulse Detected | — | Measurement status flag |
| Cuff Too Loose | — | Measurement status flag |
| Measurement Position Error | — | Measurement status flag |
| Measurement Valid | — | `True` when all status bits are 0; only present if device reports status |
| Status Flags | — | Raw status uint16 as hex (e.g. `0x0006`); diagnostic |
| Status Summary | — | Human-readable active flags, e.g. `body_movement, cuff_too_loose` or `OK` |
| Bonded Proxy | — | Diagnostic — which ESPHome proxy is pinned/last used |

### Glucose Meter

| Entity | Unit | Notes |
|--------|------|-------|
| Glucose | mmol/L | Primary reading |
| Glucose (mg/dL) | mg/dL | Always present |
| Record Sequence Number | — | Monotonic counter from device |
| Last Measurement Time | — | Device timestamp |
| Sample Type | — | e.g. `Capillary Whole Blood` |
| Sample Location | — | e.g. `Finger` |
| Device Battery Low | — | Status flag |
| Sensor Malfunction | — | Status flag |
| Result Too High | — | Status flag |
| Result Too Low | — | Status flag |
| Strip Insertion Error | — | Status flag |
| General Device Fault | — | Status flag |
| Measurement Valid | — | `True` when all status bits are 0 |
| Status Flags | — | Raw status uint16 as hex; diagnostic |
| Status Summary | — | Human-readable active flags or `OK` |
| Meal | — | Context: `Preprandial` / `Postprandial` / `Fasting` etc. |
| Tester | — | Context: `Self` / `Health Care Professional` / `Lab Test` |
| Health Status | — | Context: health notes |
| HbA1c | % | Context: if reported by device |
| Medication | — | Context: insulin type |
| Carbohydrate | — | Context: meal type |
| Bonded Proxy | — | Diagnostic — which ESPHome proxy is pinned/last used |

Context sensors are only `available` once the device has reported them.

### Weight Scale

**Always present (Weight Scale Service `0x181D`)**

| Entity | Unit | Notes |
|--------|------|-------|
| Weight | kg | |
| Weight (lb) | lb | |

**Optional — if reported by device**

| Entity | Unit |
|--------|------|
| BMI | — |
| Height | cm |
| Last Measurement Time | — |
| User ID | — |

**Body Composition (Body Composition Service `0x181B`, if available)**

| Entity | Unit |
|--------|------|
| Body Fat | % |
| Muscle Percentage | % |
| Muscle Mass | kg |
| Fat-Free Mass | kg |
| Soft Lean Mass | kg |
| Body Water Mass | kg |
| Impedance | Ω |
| Basal Metabolic Rate | kJ |

Body composition sensors are only `available` once the device has reported them.

**Bonded models only (e.g. Beurer BF 720)**

| Entity | — | Notes |
|--------|---|-------|
| Bonded Proxy | — | Diagnostic — pinned/last connected proxy |

---

## How It Works

### Blood Pressure & Glucose (notify/indicate pattern)

```
User takes measurement on device
        │
        ▼
Device broadcasts BLE advertisement
        │
        ▼
HA Bluetooth stack fires advertisement callback
        │
        ▼  (bonded-proxy pin check — see below)
BleakClient connects + pairs via ESPHome proxy
        │
        ▼  BPM: subscribe 0x2A35, drain indications, publish latest
           Glucose: subscribe 0x2A18 + 0x2A52 (RACP), request all
                    records, drain, link contexts, publish latest
        │
        ▼
DataUpdateCoordinator pushes update to sensor entities
```

Glucose meters use an explicit command/response protocol called **RACP (Record Access Control Point)**: after subscribing, the integration writes `[0x01, 0x01]` (Report All Stored Records) to `0x2A52`. The device streams all stored records and signals completion with a `[0x06, 0x00, 0x01, 0x01]` RACP response.

### Weight Scales (advertisement-triggered notify pattern)

```
User steps on scale → stable weight detected
        │
        ▼
Scale begins advertising
        │
        ▼
HA advertisement callback fires on each beacon
        │
        ▼  Payload gate: service_data[0x181D] must be non-empty
           (Beurer-specific: b'' = no measurement, b'\x01' = ready)
        │
        ▼
BleakClient connects + pairs (BF720) or connects without pairing (BF105)
        │
        ▼
Subscribe to 0x2A9D (weight) + 0x2A9C (body composition, if present)
Device streams all stored records from both services in parallel
        │
        ▼
Shared idle timer fires 3 s after last indication
Latest weight + latest BCM record merged into ScaleMeasurement
Published to HA sensors
        │
        ▼
30-minute cooldown prevents reconnecting on every beacon
```

Weight scales do not require an RACP write — they auto-stream records immediately on subscribe, same as blood pressure monitors.

---

## Bonding and ESPHome Proxy Pinning

Some devices (Beurer BF 720, most glucose meters, some blood pressure monitors) require BLE bonding. The Long Term Key (LTK) is stored in the ESPHome proxy's ESP32 flash — not in Home Assistant. This creates an important constraint: **the device must always connect through the same proxy.**

If a different proxy connects to a bonded device, the device may rotate its LTK, silently breaking the existing bond on the original proxy. You will then see repeated auth errors (`GATT error=5`) until you re-pair.

### Pinning a proxy

1. Go to **Settings → Devices & Services → [your device] → Reconfigure**.
2. Select the ESPHome proxy the device is bonded to.
3. Advertisements from any other proxy will be silently ignored.

The **Bonded Proxy** diagnostic sensor shows the current state:

| State | Meaning |
|-------|---------|
| `Unpinned` | No proxy pinned; any proxy may connect |
| `Pinned (OK)` | Last connection matched the pinned proxy |
| `Pinned (mismatch!)` | Last successful connection used a different proxy than pinned |
| `Pinned (no connection yet)` | Pinned but no successful connection since last HA restart |

The sensor's attributes also show `last_seen_proxy` (the most recently advertising source, even if filtered) and `last_connected_proxy`.

### Repair notifications

Home Assistant will raise a repair notification in **Settings → System → Repairs** when:

- **Proxy switch detected** — an advertisement arrives from a different proxy than the last successful connection, with no proxy pinned. This is the warning sign that LTK rotation is about to happen.
- **Manual pairing required** — `pair()` timed out or produced repeated auth errors. This typically means the device is waiting for a passkey or numeric comparison that stock `bluetooth_proxy` cannot surface.

Both notifications link to the Reconfigure flow for the unpair/re-pair wizard.

---

## Re-pairing a Stuck Bond

If the bond is broken (repeated auth errors, `GATT error=5`), follow this procedure:

### Step 1 — Unpair via Reconfigure

1. **Settings → Devices & Services → [your device] → Reconfigure**.
2. If prompted, select the correct proxy.
3. Check **Unpair from proxy** — this calls `client.unpair()` on the ESPHome proxy, which deletes the stale LTK from ESP32 flash via `esp_ble_remove_bond_device()`. No custom ESPHome YAML is needed for this step.

### Step 2 — Re-pair using ble_client mode

Stock `bluetooth_proxy` does not handle `ESP_GAP_BLE_PASSKEY_REQ_EVT`, so devices requiring passkey entry or numeric comparison cannot be paired through it directly. You need to temporarily switch the proxy to `ble_client` mode:

```yaml
# Temporarily replace bluetooth_proxy with this in your ESPHome proxy config:

#bluetooth_proxy:
#  active: true

esp32_ble:
  io_capability: keyboard_display

ble_client:
  - mac_address: AA:BB:CC:DD:EE:FF   # ← your device MAC
    id: my_device
    on_passkey_request:
      then:
        - logger.log: "Enter the passkey shown on the device"
        - logger.log: "Go to Developer Tools → Services → esphome.<proxy>_passkey_reply"
    on_passkey_notification:
      then:
        - logger.log:
            format: "Enter this passkey on your device: %06d"
            args: [ passkey ]
    on_numeric_comparison_request:
      then:
        - logger.log:
            format: "Compare this passkey with the one on your device: %06d"
            args: [ passkey ]
        - logger.log: "Go to Developer Tools → Services → esphome.<proxy>_numeric_comparison_reply"
    on_connect:
      then:
        - lambda: |-
            id(my_device)->pair();

api:
  actions:
    - action: passkey_reply
      variables:
        passkey: int
      then:
        - ble_client.passkey_reply:
            id: my_device
            passkey: !lambda return passkey;
    - action: numeric_comparison_reply
      variables:
        accept: bool
      then:
        - ble_client.numeric_comparison_reply:
            id: my_device
            accept: !lambda return accept;
```

Flash this config to your proxy, then trigger a measurement on the device. Watch the ESPHome logs — they will show which pairing method the device is requesting:

- **Passkey displayed on device**: Go to **Developer Tools → Services → `esphome.<proxy>_passkey_reply`** and enter the 6-digit code shown on the device.
- **Numeric comparison**: Go to **Developer Tools → Services → `esphome.<proxy>_numeric_comparison_reply`** with `accept: true` after confirming the codes match.
- **Just Works** (no confirmation needed): Pairing completes automatically.

The Reconfigure flow's **Pair with proxy** step also surfaces `passkey_reply` and `numeric_comparison_reply` as buttons so you don't have to leave the flow.

### Step 3 — Restore bluetooth_proxy

Once pairing is complete and confirmed in the ESPHome logs, restore your proxy config:

```yaml
bluetooth_proxy:
  active: true
```

Flash again. The proxy will now use the LTK stored in ESP32 flash for all future connections — bonding is transparent from here on.

---

## Automation Examples

### Blood pressure reading

```yaml
alias: Log blood pressure reading
trigger:
  - platform: state
    entity_id: sensor.my_bp_monitor_systolic_pressure
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "Blood Pressure Reading"
      message: >
        {{ states('sensor.my_bp_monitor_systolic_pressure') }}/
        {{ states('sensor.my_bp_monitor_diastolic_pressure') }} mmHg,
        Pulse: {{ states('sensor.my_bp_monitor_pulse_rate') }} bpm
```

### High glucose alert

```yaml
alias: Alert on high glucose
trigger:
  - platform: numeric_state
    entity_id: sensor.my_glucometer_glucose
    above: 10.0
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "⚠️ High Glucose"
      message: >
        {{ states('sensor.my_glucometer_glucose') }} mmol/L
        ({{ states('sensor.my_glucometer_glucose_mg_dl') }} mg/dL)
        — {{ states('sensor.my_glucometer_meal') }}
```

### Morning weight log

```yaml
alias: Log weight after morning weigh-in
trigger:
  - platform: state
    entity_id: sensor.my_scale_weight
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "Morning weight"
      message: >
        {{ states('sensor.my_scale_weight') }} kg
        (BMI {{ states('sensor.my_scale_bmi') }},
        fat {{ states('sensor.my_scale_body_fat') }}%)
```

---

## License

MIT
