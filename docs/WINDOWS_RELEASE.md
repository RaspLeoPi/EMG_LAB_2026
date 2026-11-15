# Windows installation and offline distribution

Supported target: Windows 10 22H2 / Windows 11 x64, a writable installation folder and an OpenGL-capable driver. The user confirmed Windows UI operation on 2026-11-15. Native Windows installation acceptance is separate from Linux software tests.

## 1. Offline ZIP: extract and run

Extract the complete release ZIP, then double-click `start.cmd`. No installed Python, uv, package index or network connection is needed. First launch verifies the release manifest and creates this copy's `.venv` from the bundled wheelhouse. It runs native-import and .NET checks before recording successful installation, then opens the application. Repeat launches reuse the environment.

The ZIP contains source, assets, SDK resources, documentation, licenses, verified Python, uv, .NET 8 and every locked Windows runtime wheel. It never contains another machine's virtual environment, personal data, logs, credentials or Git metadata.

Run `install.cmd` to repair. Interrupted creation can be retried even if Python stopped before writing `pyvenv.cfg`; setup records ownership before creating the environment. Unknown environment folders and symlinks are rejected. Two simultaneous installers cannot modify the same environment. Relocation rebuilds the environment offline; user recordings and models are preserved.

## 2. Clone on Windows: prepare, then run

1. Clone or download the complete repository into a writable folder.
2. Double-click `install.cmd`. Python and uv do not need to be installed already.
3. Wait for successful setup, then double-click `start.cmd`.

The interpreter search order is bundled Python, `py -3.13`, validated PATH Python, then the pinned Python download. Candidates must be Python 3.13 x64. Wrong versions or architectures are skipped. A runtime-fetch failure stops setup immediately.

The Python bootstrap prepares pinned application-local uv and .NET 8, synchronizes `pyproject.toml` / `uv.lock`, checks package compatibility and assets, and probes native application imports. uv environments and caches stay inside the repository even if the caller has conflicting environment settings. Progress is streamed; command output and setup errors are retained in `local/setup.log`. `install.cmd --no-pause` supports automated invocation. Re-running setup repairs missing dependencies and verified runtime files.

All setup stages use direct connections: inherited proxy variables are removed, `NO_PROXY=*` is set, pip configuration files are disabled, Python downloads bypass Windows proxy settings, and the initial curl download uses `--noproxy "*"`. This affects child processes only and does not change saved system settings. Separately running bare `uv sync` uses the caller's terminal settings.

## Shared runtime provenance

`scripts/runtime.lock` is the shared runtime source for both workflows. Python remains 3.13.5 with its existing SHA256 and fallback URLs. uv remains 0.11.26; its SHA256 is obtained from the official checksum URL pinned to that exact release before downloading/extracting. .NET is pinned to 8.0.34 with Microsoft's published SHA512 from the official release metadata:

[Microsoft .NET 8 release metadata](https://raw.githubusercontent.com/dotnet/core/main/release-notes/8.0/releases.json).

The runtime helper verifies cached file contents before reuse, verifies archives before extraction, retains upstream archive contents/notices and records actual artifact provenance. It does not manufacture a successful artifact record when downloads fail. Future runtime upgrades must update the shared pins deliberately; source setup does not silently select the latest .NET patch.

USB drivers, Cometa's system .NET Framework, device licenses and any missing Microsoft Visual C++ 2015–2022 x64 redistributable remain system prerequisites. Setup diagnoses native import failures and points to the required system components; it never installs drivers or enables physical output. The application-local .NET runtime is used by the Delsys SDK, not as a replacement for Cometa's .NET Framework.

## Build the offline release

On a network-enabled release host with uv:

```powershell
uv sync --locked
uv run python scripts/prepare_release.py --output dist/release-inputs
# Commit all reviewed source changes before building.
uv run python scripts/build_windows.py --inputs dist/release-inputs --output dist
```

The builder requires a clean Git tree and consistent uv lock. It evaluates dependency markers for Windows AMD64 / Python 3.13.5, downloads hash-locked wheels and checks wheel compatibility and coverage. `requirements-offline.txt` is generated from `uv.lock`, not maintained independently. The actual runtime inputs are recorded in `release-artifacts.lock.json`.

Outputs are a commit-identified ZIP and `.zip.sha256`, with every packaged file listed in `OFFLINE_RELEASE.json`. Existing ZIPs are not overwritten. To reuse downloaded wheels, place them in `dist/release-inputs/wheelhouse` and pass `--offline-inputs`; hash and coverage checks still apply. Generated releases, runtime inputs and environments stay out of Git.

## Acceptance and current limitations

On each Windows target, run `acceptance.cmd --relocation-test` in both a fresh source checkout and an extracted complete ZIP.

- Source acceptance invokes installation without requiring Python/uv and deliberately inherits unusable proxy settings to check the direct setup path.
- Offline acceptance must run with networking disconnected. It checks first/repeat setup and then runs synthetic training/replay, both renderers, all task UI workflows and actual offline WebEngine rendering.
- Relocation checks repeat setup in a path containing spaces and Chinese characters. Acceptance also checks coin route reachability using a software-only controller.
- Results go to `local/windows-acceptance.json`; output explicitly identifies source/offline mode and marks hardware as `not_run`. Installation failures also retain `local/setup.log`.

This Linux workspace blocks outgoing runtime downloads, so an actual complete Windows ZIP cannot yet be built here. Fixture archives/executables are software tests only. Windows-native setup, offline first launch and WebEngine acceptance remain pending until exercised on the real release. The existing competition baseline is deliberately unchanged and needs explicit teacher refreezing after final acceptance.

## Implementation verification (2026-11-15)

The full Linux regression suite passed **198 tests, with 3 platform/runtime skips**. The explicit four-task synthetic capture/training/export/replay smoke check passed, as did the native-import probe, shared-runtime/installer tests, uv lock check and relevant Ruff checks. Setup tests cover direct connections without changing inherited user settings, wrong Python architecture, verified runtime-cache reuse and repair, transport fallback, fatal digest failures, concurrent installers, incomplete environments, corrupt completion markers and preservation of unrelated environment folders.

Native Windows setup and network behavior cannot be executed in this Linux sandbox. The final archive build is attempted only after committing the reviewed source; download failures must remain explicit and never produce a placeholder ZIP.
