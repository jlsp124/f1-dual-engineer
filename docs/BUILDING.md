# Building F1 Dual Engineer

The fork retains the upstream single-file PyInstaller launcher architecture. Subsystems are dispatched from the same frozen executable, and the save-viewer React submodule is compiled before packaging.

## Requirements

- Windows 10/11 for the release `.exe`
- Python 3.12 or 3.13 (release validation uses 3.13)
- Poetry 2.2.1
- Node.js 22 and pnpm 10+
- Git with submodules initialized

## Build

```powershell
git submodule update --init --recursive
py -3.13 -m pip install poetry==2.2.1
py -3.13 -m poetry install --no-interaction --no-root
py -3.13 -m poetry run python scripts/build.py
```

`scripts/build.py` performs a clean frontend and PyInstaller build. The Windows output for this version is:

```text
dist\f1_dual_engineer_0.1.1.exe
```

The version and product identity come from `meta/meta.py`. `scripts/png.spec` collects frontend resources, assets, QML files, package metadata, and allowed subsystem modules.

## Validate the artifact

The smoke mode exercises the frozen launcher and writes a deterministic marker in the per-user application data directory:

```powershell
.\dist\f1_dual_engineer_0.1.1.exe --smoke-test hello-smoke
Get-Content "$env:LOCALAPPDATA\f1_dual_engineer\f1_dual_engineer_smoke_test.txt"
```

For an end-to-end dashboard check, start the frozen backend module with a test config and request its root URL. Normal users should launch the executable without arguments and start the backend in the GUI.

The binary is intentionally not code-signed. Do not disable Defender, SmartScreen, or other platform protections to build or run it.
