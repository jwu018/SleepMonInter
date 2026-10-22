# Night Night recording file format (version 1)

This is the contract between the device firmware and the software. The firmware writes one file per night to the SD card. The synthetic generator (`tools/generate_synthetic.py`) produces exactly this format, so real files should work without code changes.

> **Status: draft.** Still to be confirmed with the hardware team, especially the meaning and range of `raw_value`.

## Example

```
# night_night_format=1
# device_id=NN-DEV-01
# firmware=0.1.0
# start_utc=2026-11-03T03:12:00Z
# sample_period_ms=50
timestamp_ms,raw_value,battery_mv
0,51234,4150
50,51240,
100,51251,
...
```

## Header

Lines starting with `#` are metadata in `key=value` form, and they come before the column row.

| Key | Required | Meaning |
|---|---|---|
| `night_night_format` | yes | Format version. Currently `1`. |
| `device_id` | yes | Device code, e.g. `NN-DEV-01`. Never a patient identifier. |
| `firmware` | yes | Firmware version string. |
| `start_utc` | yes | Recording start, ISO 8601 in UTC with a `Z` suffix. |
| `sample_period_ms` | yes | Nominal time between samples. `50` (20 Hz). |

**Unknown keys are ignored**, so new keys can be added without breaking readers. The synthetic generator adds `synthetic=true`, `profile=...` and `seed=...`.

## Columns

| Column | Type | Meaning |
|---|---|---|
| `timestamp_ms` | integer | Milliseconds since `start_utc`. Nominally increases by `sample_period_ms`. |
| `raw_value` | unsigned integer | Reading from the RIP front end (e.g. oscillator frequency counts). The absolute value depends on the circuit, so **only changes are meaningful**. |
| `battery_mv` | integer or empty | Battery voltage in millivolts. It may be logged less often than every sample; rows without a reading leave it empty. The generator logs it once per minute. |

## Validation rules

- All required header keys are present.
- Timestamps are strictly increasing.
- A jump between consecutive timestamps of **more than 1 s is reported as a data gap**, but the file isn't rejected.
- Maximum file size is about 50 MB. An 8-hour night is about 10 MB.
