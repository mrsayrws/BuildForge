# BuildForge 1.1.0

Release date: 2026-11-19

This release makes detection trustworthy. BuildForge now identifies what a
folder really is instead of guessing from the first file it sees, and it
explains missing toolchains before a build starts.

## New detection

- **ESP-IDF firmware** — recognised by `sdkconfig`, `sdkconfig.defaults`,
  `idf_component_register` or the IDF `project.cmake` include. The chip target
  is read from `IDF_TARGET`, `sdkconfig` or `sdkconfig.defaults` (default
  `esp32`). This used to be mistaken for a plain CMake desktop project.
- **PlatformIO** (`platformio.ini`), **Meson** (`meson.build`), **Bazel**
  (`MODULE.bazel` / `WORKSPACE`), **qmake** (`*.pro`) and **Arduino**
  (`*.ino`, board from `sketch.yaml` / `sketch.json`).
- **Plain Python scripts** — a folder of `.py` files with no package manifest
  is now a Python project instead of `unknown`.
- **Wrapper folders** — a folder that contains exactly one project is opened
  through to that project, and the header shows `detected inside <parent>`.

## Build plans

- ESP-IDF: `idf.py -B build -j N -DCMAKE_BUILD_TYPE=Release build`, with
  `IDF_PATH` and `IDF_TARGET` in the environment.
- If `build/CMakeCache.txt` was produced by a non-IDF CMake run, the build
  goes to `buildforge-out/` instead of deleting the cache.
- PlatformIO, Arduino, Meson, Bazel and qmake plans, each with clean support.
- CMake no longer requires `make`; Gradle wrapper projects no longer require a
  global Gradle.

## Toolchain preflight

- 25 tools scanned, including `idf.py`, `pio`, `meson`, `bazel`, `qmake` and
  `arduino-cli`.
- `idf.py` is found on PATH, through `IDF_PATH`, or in the usual Espressif
  install folders (`.espressif`, `C:\Espressif`, per-user IDF python envs).
- A missing tool now highlights the row in the Toolchains tab and prints the
  exact install command. ESP-IDF shows `winget install --id Espressif.EIM-CLI`
  followed by `eim install`.

## UI

- BUILD stays clickable; when a plan is empty the app explains why instead of
  leaving a dead button.
- Switching projects clears the log and the Problems table, so old output is
  never mistaken for the current project's.
- The recently selected folder is remembered as chosen, not as the nested
  project root.
- Problems tab opens automatically after a failed build, with the usual
  file:line, WHY and FIX.

## Quality

- 83 tests (detection fixtures for every stack, ESP-IDF targets, stale-cache
  handling, toolchain preflight, runner streaming and cancel paths, store
  roundtrips, Tk smoke tests).
- Frozen Windows build: `BuildForge-1.1.0-win64.zip` (onedir, windowed, icon,
  version resource).
