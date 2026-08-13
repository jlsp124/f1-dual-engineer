# F1 Dual Engineer v0.1.1

This focused Windows hotfix fixes a startup crash when the standalone executable is launched with a protected current working directory, including `C:\Windows\System32`.

## Fixed

- Windows logs, settings, performance data, crash diagnostics, automatic captures, lock state, and default session exports now use `%LOCALAPPDATA%\f1_dual_engineer\` instead of the process current working directory.
- Required application-data directories are created before use.
- User-selected absolute export directories remain unchanged.
- The frozen-launcher release smoke test now runs from a non-project directory and rejects any mutable files written beneath that directory.

There are no UI, telemetry-analysis, or product-feature changes in this release. macOS and Linux runtime-path behavior is unchanged.

## Install

Download `f1_dual_engineer_0.1.1.exe` and compare its SHA-256 digest with `checksums.txt`. The executable is unsigned, so Windows SmartScreen may show an unrecognized-app warning.

## Attribution

Derived from [Pits n' Giggles](https://github.com/ashwin-nat/pits-n-giggles) 4.3.0 at commit `0cc3484`, under the MIT License. This is an independent project and not an official upstream release.
