# F1 Dual Engineer v0.1.0

The first independent release turns the Pits n' Giggles telemetry foundation into a dual-driver pit wall for F1 25 while retaining its useful single-driver dashboard, overlays, save viewer, and tooling.

## Highlights

- Permanent Driver A and Driver B live cards with privacy-aware detail.
- Full timing tower, live track map, distance-normalized trace comparison, and prioritized engineer feed.
- Automatic raw/structured recording and end-of-session CSV/JSON analysis exports.
- Explainable time-loss diagnoses, entry/mid/exit breakdown, reference quality, clean-lap theoretical pace, and consistency.
- Local SQLite career companion with import, observed results, standings, live projection, and head-to-head.
- Clearly labelled offline demo mode.
- Standalone Windows executable; no Python installation required.
- Security-hardened UDP fault isolation, same-origin local APIs, bounded uploads/recording, safe retention, inert DOM/CSV rendering, and defensive capture parsing.

## Install

Download `f1_dual_engineer_0.1.0.exe` and compare its SHA-256 digest with `checksums.txt`. The executable is unsigned, so Windows SmartScreen may show an unrecognized-app warning.

Configure F1 25 for UDP Format 2025, 60 Hz, the engineer laptop's IP, and port 20777. Remote players should select Public telemetry visibility for detailed car data.

## Known limitations

- Remote detail is limited by F1 25 privacy and player-specific packets.
- Wheel-level slip data cannot be claimed for arbitrary remote drivers.
- Career history editing is limited to re-importing corrected current standings in 0.1.0.
- Segment labels fall back to stable distance windows when official corner geometry is unavailable.
- The Windows binary is not code-signed.
- The inherited classic dashboards still fetch pinned frontend libraries/fonts from third-party CDNs; the primary Dual Engineer screen does not.

## Attribution

Derived from [Pits n' Giggles](https://github.com/ashwin-nat/pits-n-giggles) 4.3.0 at commit `0cc3484`, under the MIT License. This is an independent project and not an official upstream release.
