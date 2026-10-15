# JK BMS settings

With `jk_settings: true` batmon reads the settings of JK BMSes (protection voltages, currents, temperatures,
balancer, switches) and shows them in Home Assistant. Settings you list in a device's `settings_write` can be
changed from Home Assistant. Every write is checked, backed up, verified by reading it back and logged.

Off by default. Without `settings_write` everything stays read-only.

## Supported BMS

* JK BMS over Bluetooth with the JK02_32S protocol (firmware 11 and newer, `type: jk` or `jk_32s`).
* Tested on a JK-B2A8S30P, hardware 15A / firmware 15.26 and hardware 17H / firmware 17.06
  (Raspberry Pi 4, bleak 2.0.0). Other JK models with the same protocol should work, but are untested.
* JK-PB over UART (`jk_pb_uart`), older JK firmware (`jk_24s`) and all other BMS types: unchanged, no settings.

## Options

```yaml
jk_settings: true            # global: read the settings and show them in Home Assistant
devices:
  - address: C8:47:8C:E4:55:E5
    type: jk
    alias: jk_bms1
    settings_write: all      # per device: which settings may be changed
```

`settings_write` is `all`, a comma-separated list of setting names, or both, e.g.
`all, cell_count` or `cell_ovp, cell_ovpr, charge_utp, charge_utpr`.

* `all` means every writable setting **except the critical ones**. Critical settings that can be written must be
  named explicitly: `cell_count`, `disable_temperature_sensors`, `gps_locked_charging`, `gps_locked_discharging`.
  A wrong value there can stop the BMS from protecting the pack, or lock charging/discharging.
* A name that is unknown or not writable (see the table below) is a configuration error: batmon logs it, the
  device stays **read-only** (nothing is writable) and the error is shown in the `Settings last change` sensor.
  batmon keeps running.
* `settings_write` without `jk_settings: true` does nothing.
* The setting `current_calibration` below is the BMS's own calibration; it is not batmon's per-device
  `current_calibration` option.

## Home Assistant entities

All entities belong to the BMS device in Home Assistant.

* Settings named in `settings_write`: config entities (`number` as an input box with the range and step from
  the table, or `switch`).
* All other readable settings: diagnostic `sensor` / `binary_sensor`. They expire after 2 hours (or
  `expire_values_after`, if longer) without an update.
* `Settings last change` (diagnostic sensor): the result of the last request, one of
  * `OK cell_ovp 3.65 -> 3.6V`
  * `Unchanged cell_ovp 3.65V` (the BMS already has this value, nothing was written)
  * `Rejected cell_ovp 4.5: <reason>` (nothing was written, the entity snaps back to the BMS value)
  * `FAILED cell_ovp 3.6 read back 3.65; writes locked`
  * `Config error: <reason>` (bad `settings_write`)
* On a JK-PB with a built-in float charger, `charging_float_mode` gets no entity of its own: it is already the
  `float_charge` switch.

Settings are read when batmon starts, every 5 minutes, before each change and right after it. If reading fails,
the next try is 60 seconds later; requests made meanwhile wait in a queue (at most 20 per BMS, more are rejected
with `queue full`).

Config entities (number/switch) have no expiry in Home Assistant: while batmon or the BMS is offline they keep
showing the last value. Check that the device is online before trusting them.

## Settings

Write: `all` = included in `all`; *by name* = critical, only when named; *no (unverified)* = shown read-only, the
write format or read offset is not verified on hardware yet; *no (not readable)* = not in the BMS's settings frame,
so a write could not be verified; not shown and not writable. Risk is a rough guide to what a wrong value can do.

| Name | Label in HA | Range, step | Risk | Write |
|---|---|---|---|---|
| `smart_sleep_voltage` | Smart sleep voltage | 0.003 … 3.65 V, step 0.001 | low | no (unverified) |
| `cell_uvp` | Cell UVP | 1.2 … 4.35 V, step 0.001 | high | `all` |
| `cell_uvpr` | Cell UVPR | 1.2 … 4.35 V, step 0.001 | high | `all` |
| `cell_ovp` | Cell OVP | 1.2 … 4.35 V, step 0.001 | high | `all` |
| `cell_ovpr` | Cell OVPR | 1.2 … 4.35 V, step 0.001 | high | `all` |
| `balance_trigger_voltage` | Balance trigger voltage | 0.003 … 1 V, step 0.001 | med | `all` |
| `cell_soc100_voltage` | SOC 100% voltage | 0.003 … 3.65 V, step 0.001 | med | `all` |
| `cell_soc0_voltage` | SOC 0% voltage | 0.003 … 3.65 V, step 0.001 | med | `all` |
| `cell_rcv` | Cell RCV | 0.003 … 3.65 V, step 0.001 | med | `all` |
| `cell_rfv` | Cell RFV | 0.003 … 3.65 V, step 0.001 | med | `all` |
| `power_off_voltage` | Power off voltage | 1.2 … 4.35 V, step 0.001 | high | `all` |
| `max_charge_current` | Max charge current | 1 … 600.1 A, step 0.001 | high | `all` |
| `charge_ocp_delay` | Charge OCP delay | 2 … 600 s, step 1 | med | `all` |
| `charge_ocpr_time` | Charge OCPR time | 2 … 600 s, step 1 | med | `all` |
| `max_discharge_current` | Max discharge current | 1 … 1200.1 A, step 0.001 | high | `all` |
| `discharge_ocp_delay` | Discharge OCP delay | 2 … 600 s, step 1 | med | `all` |
| `discharge_ocpr_time` | Discharge OCPR time | 2 … 600 s, step 1 | med | `all` |
| `scpr_time` | SCPR time | 2 … 600 s, step 1 | med | `all` |
| `max_balance_current` | Max balance current | 0.3 … 15 A, step 0.001 | med | `all` |
| `charge_otp` | Charge OTP | 30 … 80 °C, step 0.1 | high | `all` |
| `charge_otpr` | Charge OTPR | 30 … 80 °C, step 0.1 | high | `all` |
| `discharge_otp` | Discharge OTP | 30 … 80 °C, step 0.1 | high | `all` |
| `discharge_otpr` | Discharge OTPR | 30 … 80 °C, step 0.1 | high | `all` |
| `charge_utp` | Charge UTP | -45 … 20 °C, step 0.1 | high | `all` |
| `charge_utpr` | Charge UTPR | -45 … 20 °C, step 0.1 | high | `all` |
| `mosfet_otp` | MOSFET OTP | 50 … 110 °C, step 0.1 | high | `all` |
| `mosfet_otpr` | MOSFET OTPR | 50 … 110 °C, step 0.1 | high | `all` |
| `cell_count` | Cell count | 2 … 32, step 1 | critical | by name |
| `total_capacity` | Total capacity | 2 … 20000 Ah, step 0.001 | high | `all` |
| `scp_delay` | SCP delay | 0 … 1000000 µs, step 1 | high | `all` |
| `balance_start_voltage` | Balance start voltage | 1.2 … 4.25 V, step 0.001 | med | `all` |
| `precharge_time` | Precharge time | 0 … 255 s, step 1 | med | no (unverified) |
| `heating_start_temp` | Heating start temp | -40 … 100 °C, step 1 | med | no (unverified) |
| `heating_stop_temp` | Heating stop temp | -40 … 100 °C, step 1 | med | no (unverified) |
| `smart_sleep_delay` | Smart sleep delay | 1 … 100 h, step 1 | low | `all` |
| `discharge_utp` | Discharge UTP | -40 … 100 °C, step 1 | high | no (unverified) |
| `discharge_utpr` | Discharge UTPR | -40 … 100 °C, step 1 | high | no (unverified) |
| `rcv_time` | RCV time | 0 … 18.2 h, step 0.1 | low | no (not readable) |
| `rfv_time` | RFV time | 0 … 18.2 h, step 0.1 | low | no (not readable) |
| `emergency_duration` | Emergency duration | 1 … 255 min, step 1 | med | no (not readable) |
| `re_bulk_soc` | Re-bulk SOC | 0 … 50 %, step 1 | low | no (not readable) |
| `voltage_calibration` | Voltage calibration | 1 … 200 V, step 0.001 | critical | no (not readable) |
| `current_calibration` | Current calibration | 0 … 1000 A, step 0.001 | critical | no (not readable) |
| `heating` | Heating | ON/OFF | med | `all` |
| `disable_temperature_sensors` | Disable temperature sensors | ON/OFF | critical | by name |
| `display_always_on` | Display always on | ON/OFF | low | `all` |
| `smart_sleep` | Smart sleep | ON/OFF | low | `all` |
| `disable_pcl_module` | Disable PCL module | ON/OFF | med | `all` |
| `timed_stored_data` | Timed stored data | ON/OFF | low | `all` |
| `charging_float_mode` | Charging float mode | ON/OFF | med | `all` |
| `emergency_button_trigger` | Emergency button trigger | ON/OFF | low | `all` |
| `dry_contact_alarm_intermittent` | Dry contact alarm intermittent | ON/OFF | low | `all` |
| `discharge_ocp2` | Discharge OCP2 | ON/OFF | med | `all` |
| `discharge_ocp3` | Discharge OCP3 | ON/OFF | med | `all` |
| `gps_locked_charging` | GPS locked charging | ON/OFF | critical | by name |
| `gps_locked_discharging` | GPS locked discharging | ON/OFF | critical | by name |

Not here on purpose: the charge/discharge/balance switches and SOC calibration (already batmon's own
switches and `set_soc` number), SOH calibration and the emergency switch (not readable, so not verifiable).

## What happens on a change

Each request goes through these steps; the first one that fails ends it, and nothing is written:

1. **Whitelist**: the setting must be in the device's `settings_write`.
2. **Unchanged?** Switches take `ON`/`OFF`, numbers a number. If the BMS already has the value, nothing is
   written (`Unchanged`).
3. **Range and step**: numbers must be within the range and a multiple of the step in the table above.
4. **Cross-field rules** against the values just read from the BMS. Only rules that involve the changed setting
   are checked, and only when the other value is known:
   * `cell_uvp` < `cell_uvpr`, `cell_ovpr` < `cell_ovp`
   * `charge_utp` < `charge_utpr`, `discharge_utp` < `discharge_utpr`
   * `charge_otpr` < `charge_otp`, `discharge_otpr` < `discharge_otp`, `mosfet_otpr` < `mosfet_otp`
   * `power_off_voltage` < `cell_uvp`
   * `cell_soc0_voltage` < `cell_soc100_voltage` ≤ `cell_rcv` < `cell_ovp`
   * `cell_rfv` < `cell_rcv`
5. **Lock**: no write while this BMS is locked (see below).
6. **Backup** of all settings, once per batmon run, before the first write. If the backup cannot be written,
   nothing is written.
7. **Write** the one setting, wait, **read** the settings back and **compare**. There are no retries.
8. **Audit**: every write attempt is logged to `settings_audit.jsonl`.

### Protection and recovery values: which one first

Like the JK app, batmon keeps every protection value on the safe side of its recovery value (the rules in step 4).
To move both, change them in the right order, otherwise the first change is rejected:

* Raising a low limit (e.g. `charge_utp` from 0 to 5 °C while `charge_utpr` is 5 °C): raise the recovery value
  `charge_utpr` first, then `charge_utp`. Same for `cell_uvpr` before `cell_uvp`.
* Lowering a high limit (e.g. `charge_otp`): lower the recovery value `charge_otpr` first, then `charge_otp`.
  Same for `cell_ovpr` before `cell_ovp`, and the discharge/MOSFET OTP pairs.

The rejection says which one to change first, e.g.
`Rejected charge_utp 6: charge_utp 6°C must be below charge_utpr (5°C); change charge_utpr first`.

### Read-back mismatch: writes locked

If the value read back differs from the one written, the BMS did not take it (or took something else).
batmon shows `FAILED … writes locked`, logs it, and refuses **all** further writes to this BMS until batmon
restarts. Reading continues. Check the value in Home Assistant or the JK app, fix it if needed, then restart
batmon (restart the add-on) to unlock.

### Bluetooth error during a write

If the connection fails during the write or the read-back (`Rejected …: BLE error: …`), batmon cannot tell
whether the BMS took the value. Writes are **not** locked in this case. The next settings read (at the latest
5 minutes later) shows the real value: check it before trying again.

## Files

Stored in the add-on's data directory (`/data`, part of the add-on's backup) or, outside Home Assistant, in
batmon's working directory:

* `settings_backup/<alias>-<UTC time>.json`, e.g. `settings_backup/jk_bms1-20261015T081500Z.json`: all settings
  as read before the first write of a batmon run (`settings`), plus the raw settings frame (`raw_hex`).
* `settings_audit.jsonl`: one JSON line per write attempt with `time`, `alias`, `name`, `before`, `requested`,
  `after`, `ok` and `reason`.

### Restore

There is no automatic restore. Take the values from the backup's `settings` block and set them again, one by one,
in Home Assistant or in the JK app. Mind the protection/recovery order above.

## One Bluetooth connection

A JK BMS accepts only one Bluetooth connection at a time. Close the JK app before changing settings through
batmon, and stop batmon before using the app.

## Web GUI

The web GUI stays read-only; it does not show or change settings (see [GUI.md](GUI.md)).
