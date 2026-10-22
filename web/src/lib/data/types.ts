// Shapes of the data the dashboard works with. Field names are snake_case on purpose:
// they match the JSON files today and the FastAPI responses later (Phase 3), so swapping
// the data source doesn't ripple through the UI.

export type Quality = "good" | "poor" | "no_signal";

/** One night, as listed on the patient overview. */
export interface RecordingSummary {
  recording_id: string;
  study_code: string;
  device_id: string;
  start_utc: string; // ISO 8601, UTC
  end_utc: string;
  duration_min: number;
  battery_start_mv: number;
  battery_end_mv: number;
  gap_count: number;
  median_resp_rate_bpm: number | null;
  mean_amplitude_rel: number | null;
  pct_good: number;
  pct_poor: number;
  pct_no_signal: number;
}

export interface PatientSummary {
  study_code: string;
  device_id: string;
  recording_count: number;
  last_recording_start_utc: string | null;
}

export interface Patient extends PatientSummary {
  recordings: RecordingSummary[];
}

/** Per-minute metrics stored column by column (one array per field, same length). */
export interface MinuteMetrics {
  minute_index: number[];
  resp_rate_bpm: (number | null)[];
  amplitude_rel: (number | null)[];
  quality: Quality[];
}

export interface RecordingDetail extends RecordingSummary {
  sample_period_ms: number;
  status: "uploaded" | "processing" | "processed" | "failed";
  metrics: MinuteMetrics;
}

/** A downsampled slice of the raw signal, ready to plot. */
export interface WaveformWindow {
  start_ms: number; // ms since recording start
  end_ms: number;
  t_ms: number[];
  raw_value: (number | null)[]; // null = data gap
  /** "raw" = every 10 Hz point; "envelope" = min/max pairs per bucket (zoomed out). */
  resolution: "raw" | "envelope";
}
