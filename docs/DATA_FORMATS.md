# Session data formats

F1 Dual Engineer writes session data incrementally outside the telemetry ingest hot path. A bounded queue prevents unbounded memory growth; queue-drop counters are included in `session_summary.json`.

Capture entries are length-checked and decompressed with a 64 KiB per-packet ceiling. Capture imports also validate the header, stored size, entry count, source-file size, and cumulative expansion before retaining packets.

## Files

- `raw_telemetry.f1pcap`: every retained UDP datagram in replay-compatible F1PktCap 1.1 format, individually zlib-compressed with receipt timestamps. This is the source for future deeper re-analysis.
- `telemetry_samples.csv`: selected-driver analysis rows at the configured structured sample rate (20 Hz default). Columns cover lap/time/distance, privacy availability, speed, inputs, gear/RPM, G-force, world position, tyres, fuel, ERS, DRS, damage, weather, safety-car state, pit state, and invalid-lap status.
- `classification.csv`: final classification facts when the game emits them.
- `laps.csv`: lap and sector history available from the final session snapshot.
- `driver_a_vs_driver_b.csv`: synchronized distance-based comparison points for comparable selected-driver laps.
- `corner_analysis.csv`: segment label/range, measured loss, phase split, diagnosis, confidence, and evidence.
- `session_summary.json`: schema/version metadata, capture counters, original final-session structure, comparison summary, theoretical lap and reference quality when available.
- `f1_dual_engineer.sqlite`: career configuration, imported bases, observed events/results, recorded-session catalog, and preferences.

Partial recordings use `.part` suffixes. They are atomically renamed during finalization. A recording interrupted by a hard power loss may retain a partial folder rather than presenting incomplete data as finalized.

## Why CSV instead of Parquet

The 0.1.0 release prioritizes a single reliable Windows executable and broadly interoperable output. Raw packets preserve full fidelity, while CSV keeps structured exports inspectable without adding a large native Arrow dependency. A later version can add optional Parquet without replacing the raw capture.
