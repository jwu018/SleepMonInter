# Night Night device CSV format (firmware 0.1 / 0.2)

This is what the **real logger firmware** writes to the microSD card today. It's different from
the format the synthetic generator writes (`docs/FILE_FORMAT.md`); see "Differences" below.
The upload page (`/upload`) reads this format.

Source: the firmware team's description, checked against five bench recordings from firmware
0.1 (2026-10-26). Those files had no sensor attached, so the sensor columns are untested on
real data so far.

## File name and location

- One file per recording: `S<YYYYMMDD>_<HHMMSS>.csv`, named from the device clock at start,
  e.g. `S20261026_205511.csv`.
- If two recordings start in the same second, the second gets a suffix: `S20261026_205511_01.csv`.
- Other files on the card (`sdtest.csv`, macOS `._*` files, `.Trashes`,
  `System Volume Information`) are not recordings and are ignored.

## Example

```
# Night Night respiratory logger, firmware 0.2
# start_local,2026-10-26 21:23:56
# rtc,DS3231 ok
# sample_rate_hz,25
# ldc1612,channel 0, tank 100 pF, drive 20
datetime,elapsed_ms,sample,ldc_raw,ldc_freq_hz,ldc_L_uH,ldc_flags,a0_raw
2026-10-26 21:23:56.038,0,0,21735392,3238825.8,24.14711,1,161
2026-10-26 21:23:56.078,40,1,21735413,3238828.9,24.14706,1,669
...
# drift_check,2026-10-26 21:33:56.020,elapsed_ms=600020,drift_ms=2,resolution_ms=+/-20
...
# stop,2026-10-26 21:25:53.768,reason=serial,rows=2944,missed_slots=0
```

## Comment lines (`#`)

Header lines come first. Event lines can appear anywhere after the column row.

| Line | Meaning |
|---|---|
| `# Night Night respiratory logger, firmware X` | Firmware version. |
| `# start_local,<YYYY-MM-DD HH:MM:SS>` | Start time from the device clock (local time, **no time zone**). |
| `# rtc,<status>` | Real-time clock status, e.g. `DS3231 ok`. |
| `# sample_rate_hz,<n>` | Nominal sample rate. 25 Hz (one sample every 40 ms). |
| `# ldc1612,<settings>` | Inductance sensor settings, or `NOT FOUND (sensor columns blank)` if no sensor answered. |
| `# drift_check,<datetime>,elapsed_ms=…,drift_ms=…,resolution_ms=…` | Every 10 minutes: how far the clock has drifted from the elapsed-time counter. |
| `# stop,<datetime>,reason=…,rows=…,missed_slots=…` | Last line of a cleanly ended file. **Missing if power was cut.** Observed reasons: `serial`, `time_set`. |

## Columns

| Column | Meaning |
|---|---|
| `datetime` | Device clock time, millisecond resolution, local time with no time zone or DST info. Can be wrong if the clock was reset. |
| `elapsed_ms` | Milliseconds since the recording started. Always reliable, even when the clock isn't. |
| `sample` | Scheduled sample index. **A jump greater than 1 means dropped samples.** |
| `ldc_raw` | Raw 28-bit count from the LDC1612 sensor. |
| `ldc_freq_hz` | Sensor oscillation frequency. Rises when belt inductance falls. |
| `ldc_L_uH` | Belt inductance in microhenries: **the breathing signal**. |
| `ldc_flags` | Bit flags: 8 = under-range, 4 = over-range, 2 = watchdog / no oscillation, 1 = amplitude warning. 0 = clean. |
| `a0_raw` | Unused auxiliary analog input. Debug only. |

Sensor columns are blank when the sensor isn't connected.

## Observed in the bench files

- The interval is 40 ms almost always. One file had a single 58 ms gap followed by a 22 ms catch-up.
- No `sample` jumps (no dropped samples) and `missed_slots=0` in every stop line.
- Two of five files have no `# stop` line (power was removed before stopping).
- One file's first row has `elapsed_ms=1`, not 0.

## Differences from the synthetic format (`docs/FILE_FORMAT.md`)

| | Synthetic format v1 | Device firmware 0.1/0.2 |
|---|---|---|
| Header | `# key=value` | `# key,value` (comma), plus a free-text first line |
| Start time | `start_utc`, UTC | `start_local`, device local time, no time zone |
| Sample rate | 20 Hz (`sample_period_ms=50`) | 25 Hz (`sample_rate_hz=25`) |
| Signal | `raw_value` (generic counts) | `ldc_L_uH` (inductance), plus `ldc_raw` and `ldc_freq_hz` |
| Battery | `battery_mv` column | **none** |
| Device ID | `device_id` header | **none** (only the file name and settings) |
| Integrity info | data gaps from timestamps | `sample` index, `ldc_flags`, `drift_check`, `stop` line |

Status (2026-10-27): the format is still being finalized with the firmware team. A **device ID** (header) and **battery voltage** (column) were left out by accident and are planned; the dashboard needs both (linking a card to a patient, and the battery panel).

Open questions for the firmware team:
- Exact names and placement for the device ID and battery fields (e.g. `# device_id,NN-DEV-01` and a `battery_mv` column logged once a minute, blank otherwise).
- Is `ldc_flags = 1` (amplitude warning) expected on every row, as in the example above? If so, it shouldn't count as a data problem.
- Can `start_local` include a UTC offset, so times stay correct across time zones and DST changes?
