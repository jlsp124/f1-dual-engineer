# Running F1 Dual Engineer

## Standalone Windows release

Download `f1_dual_engineer_0.1.1.exe` from the GitHub release and launch it from any folder. The launcher manages the telemetry backend, HUD, save viewer, broker, and other inherited tools. Start **Telemetry Backend**; the dual-driver dashboard opens at `http://127.0.0.1:4768/`.

On Windows, logs, settings, databases, automatic captures, crash diagnostics, lock state, and the default exports directory are stored under `%LOCALAPPDATA%\f1_dual_engineer\`. A user-selected absolute export directory is preserved.

The binary is not code-signed. Windows SmartScreen may require the normal **More info → Run anyway** confirmation. Compare the file's SHA-256 digest with the release checksum before accepting that warning.

## F1 25 / console setup

The game and app do not need to share a computer. In F1 25 telemetry settings:

1. Set **UDP Telemetry** to On.
2. Set **UDP IP Address** to the engineer laptop's LAN IPv4 address. Run `ipconfig` on that laptop and use the active Wi-Fi/Ethernet adapter's IPv4 address.
3. Set **UDP Port** to `20777` unless you changed **Network → F1 UDP Telemetry Port**.
4. Set **UDP Send Rate** to 60 Hz.
5. Set **UDP Format** to 2025.
6. Enable names/show UDP data where offered.
7. Set **Your Telemetry** to Public for remote players whose detailed inputs, tyres, fuel, ERS, and damage should be available.

Permit inbound UDP on that port through Windows Firewall for private networks. Do not expose the HTTP dashboard to the internet.

## First use

- **Network:** `127.0.0.1` is the safe dashboard default. UDP still accepts console/PC telemetry on the configured port. Use `0.0.0.0` only to intentionally let trusted LAN devices open the dashboard.
- **Engineer:** automatic recording is on, structured sampling defaults to 20 Hz, `exports` is the default output folder, retention is unlimited (`0` days), and all alert categories are enabled.
- **Driver selection:** select two different participants on Dual Pit Wall and click **Pin Drivers**. Stored names are used to restore the pair when possible.
- **Privacy:** restricted remote detail is displayed as `Unavailable`. It is not reconstructed or guessed.

Use `http://127.0.0.1:4768/?demo=1` to inspect the complete interface without game telemetry. The orange `DEMO DATA` badge remains visible throughout.

## Development run

From the repository root on Windows:

```powershell
git submodule update --init --recursive
py -3.13 -m pip install poetry==2.2.1
py -3.13 -m poetry install --no-interaction --no-root
py -3.13 -m poetry run python -m apps.launcher
```

Run the backend without the launcher:

```powershell
py -3.13 -m poetry run python -m apps.backend
```

Replay an existing `.f1pcap` during development:

```powershell
py -3.13 -m poetry run python -m apps.backend --replay-server
py -3.13 -m poetry run python -m apps.dev_tools.telemetry_replayer --file-name path\to\capture.f1pcap
```

All commands must run from the project root.
