"""Night Night signal processing: belt inductance -> breaths -> respiratory rate.

The pipeline, in order (see `pipeline.process_trial`):

    load.load_trial            raw file -> evenly spaced samples (NaN where samples were lost)
    filters.remove_glitches    YOU WRITE (step 2): drop physically impossible readings
    load.fill_short_gaps       bridge short holes so the filter can run
    filters.bandpass           YOU WRITE (step 2): keep only breathing frequencies (0.1-1 Hz)
    breaths.detect_breaths     YOU WRITE (step 3): find each inhale peak and exhale trough
    metrics.*                  YOU WRITE (step 4): count, per-minute rate, amplitude, pauses

Functions marked YOU WRITE raise NotImplementedError until you fill them in. Their docstrings
describe the inputs, outputs and the cases they must handle; tests in
`tests/test_processing.py` are the targets (they show as "xfail" until implemented).

Everything else (loading, gap filling, plotting, the trial report) is scaffolding that
already works.
"""
