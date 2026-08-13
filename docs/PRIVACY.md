# Privacy and network security

F1 Dual Engineer is local-first. It has no analytics, account, cloud sync, telemetry upload, or external coaching service. The embedded save-viewer build has analytics disabled. The primary Dual Engineer interface is fully self-hosted. Inherited Classic Engineer, Single Driver, track-map, and stream-overlay pages still download pinned UI libraries and fonts from jsDelivr, cdnjs, and Google Fonts when opened; those providers receive ordinary web-request metadata, but F1 telemetry is not placed in their URLs.

## Network surfaces

- F1 UDP listens on the configured telemetry port so consoles and gaming PCs can send packets to the engineer laptop.
- HTTP dashboards bind to `127.0.0.1` by default.
- Choosing `0.0.0.0` intentionally exposes the dashboards to the local network. There is no authentication layer; use it only on a trusted private LAN and never port-forward the dashboard.
- Mutation routes enforce same-origin requests. Opening a local session folder additionally requires a loopback client and cataloged session path.
- Dashboard Host and Origin values are independently allowlisted; Socket.IO also has origin, message-size, and connection-count bounds.

## Stored data

Raw F1 packets can contain participant names, session identifiers, vehicle state, and positions. Career imports contain names and points supplied by the user. Treat exported sessions as personal data and review them before sharing.

Automatic recording defaults to a 2 GiB raw cap per session, a 20 GiB application-owned export cap, and a 2 GiB free-space floor. These are adjustable in Engineer settings. When a threshold is reached, new recording writes are refused rather than allowing unbounded disk growth.

The repository ignores `exports/`, SQLite databases and journals, configs, logs, `.f1pcap`, CSV/JSON captures, ZIP exports, and generated builds. Demo screenshots use representative synthetic data and are visibly labelled.

## Telemetry availability

F1 25 privacy settings control which detailed packets are available for remote players. The app marks restricted values unavailable. It does not infer private throttle, brake, tyres, fuel, ERS, or damage and present them as measured facts.
