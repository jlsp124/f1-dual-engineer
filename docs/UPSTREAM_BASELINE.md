# Upstream baseline

F1 Dual Engineer preserves the history and architecture of Pits n' Giggles so
future upstream fixes can be reviewed and merged selectively.

- Upstream: <https://github.com/ashwin-nat/pits-n-giggles>
- Baseline commit: `0cc3484`
- Upstream version at fork: `4.3.0`
- Local upstream remote: `upstream`
- Fork version: `0.1.0`
- License: MIT; see [LICENSE](../LICENSE) and [NOTICE.md](../NOTICE.md)

## Verified architecture

The telemetry core receives and parses F1 UDP packets, applies them through a
single-writer in-memory session state, and publishes lower-frequency snapshots
to browser clients through Quart and Socket.IO. The PySide launcher manages the
backend, HUD, save viewer, broker, and optional MCP process. Browser views use
plain HTML, CSS, and JavaScript. The Windows release uses the existing
PyInstaller launcher build and embeds the save-viewer React submodule.

F1 Dual Engineer extends this architecture. High-frequency packet callbacks
remain CPU-bound and enqueue bounded recording work; persistence and analysis
run outside the ingest hot path.

## Reproduced baseline

On Windows with Python 3.13.5 and the locked Poetry dependencies:

```text
py -3.13 -m poetry run pytest tests/
1020 passed in 42.95s
```

This result was recorded before fork modifications.
