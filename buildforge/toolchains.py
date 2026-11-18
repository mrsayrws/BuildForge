from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

TOOLS: list[tuple[str, str, list[str], str, str]] = [
    ("g++", "C / C++", ["--version"], "MinGW-w64 GCC (C++ compiler)",
     "winget install --id BrechtSanders.WinLibs.POSIX.UCRT"),
    ("gcc", "C / C++", ["--version"], "MinGW-w64 GCC (C compiler)",
     "winget install --id BrechtSanders.WinLibs.POSIX.UCRT"),
    ("gdb", "C / C++", ["--version"], "GNU debugger",
     "winget install --id BrechtSanders.WinLibs.POSIX.UCRT"),
    ("cl", "C / C++", [], "MSVC compiler (Visual Studio)",
     "winget install --id Microsoft.VisualStudio.2022.BuildTools"),
    ("msbuild", "C / C++", ["-version"], "MSBuild",
     "winget install --id Microsoft.VisualStudio.2022.BuildTools"),
    ("cmake", "Build tools", ["--version"], "CMake",
     "winget install --id Kitware.CMake"),
    ("make", "Build tools", ["--version"], "GNU make",
     "winget install --id BrechtSanders.WinLibs.POSIX.UCRT"),
    ("ninja", "Build tools", ["--version"], "Ninja",
     "winget install --id Ninja-build.Ninja"),
    ("meson", "Build tools", ["--version"], "Meson build system",
     "winget install --id mesonbuild.meson"),
    ("bazel", "Build tools", ["--version"], "Bazel",
     "winget install --id Bazel.Bazel"),
    ("dotnet", "C# / .NET", ["--version"], ".NET SDK",
     "winget install --id Microsoft.DotNet.SDK.8"),
    ("node", "Web / Node", ["--version"], "Node.js",
     "winget install --id OpenJS.NodeJS.LTS"),
    ("npm", "Web / Node", ["--version"], "npm",
     "Comes with Node.js"),
    ("python", "Python", ["--version"], "Python",
     "winget install --id Python.Python.3.12"),
    ("cargo", "Rust", ["--version"], "Cargo",
     "winget install --id Rustlang.Rustup"),
    ("rustc", "Rust", ["--version"], "rustc",
     "winget install --id Rustlang.Rustup"),
    ("go", "Go", ["version"], "Go",
     "winget install --id GoLang.Go"),
    ("java", "Java", ["-version"], "Java runtime",
     "winget install --id EclipseAdoptium.Temurin.21.JDK"),
    ("javac", "Java", ["-version"], "javac",
     "winget install --id EclipseAdoptium.Temurin.21.JDK"),
    ("mvn", "Java", ["-version"], "Maven",
     "winget install --id Apache.Maven"),
    ("gradle", "Java", ["--version"], "Gradle",
     "winget install --id Gradle.Gradle"),
    ("pio", "Embedded", ["--version"], "PlatformIO CLI",
     "pip install platformio"),
    ("idf.py", "Embedded", [], "ESP-IDF build tool",
     "winget install --id Espressif.EIM-CLI   (then run: eim install)"),
    ("arduino-cli", "Embedded", ["version"], "Arduino CLI",
     "winget install --id ArduinoSA.CLI"),
    ("qmake", "Qt", ["-v"], "Qt qmake",
     "Install Qt (qt.io) and add qmake to PATH"),
]

REQUIRED = {
    "cmake": ("cmake",),
    "make": ("make",),
    "cpp": ("g++",),
    "c": ("gcc",),
    "dotnet": ("dotnet",),
    "node": ("node", "npm"),
    "python": ("python",),
    "rust": ("cargo",),
    "go": ("go",),
    "maven": ("mvn", "java"),
    "gradle": ("gradle", "java"),
    "msvc": ("msbuild", "cl"),
    "platformio": ("pio",),
    "meson": ("meson", "ninja"),
    "bazel": ("bazel",),
    "arduino": ("arduino-cli",),
    "qmake": ("qmake", "make"),
}


def _idf_python(idf_path: Path) -> str | None:
    candidates: list[Path] = []
    tools_path = os.environ.get("IDF_TOOLS_PATH")
    bases = [Path(tools_path)] if tools_path else []
    bases += [Path.home() / ".espressif", idf_path, idf_path.parent]
    for base in bases:
        try:
            envs = sorted((base / "python_env").glob("idf*_env"), reverse=True)
        except OSError:
            continue
        for env in envs:
            candidates += [env / "Scripts" / "python.exe", env / "bin" / "python"]
    candidates += [idf_path / ".venv" / "Scripts" / "python.exe",
                   idf_path / ".venv" / "bin" / "python"]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _candidate_idf_paths() -> list[Path]:
    paths: list[Path] = []
    env = (os.environ.get("IDF_PATH") or "").strip()
    if env:
        paths.append(Path(env))
    home = Path.home()
    for base in (home / "esp", home / "Espressif", Path("C:/Espressif"),
                 home / ".espressif" / "frameworks"):
        try:
            paths += [p for p in sorted(base.glob("esp-idf*"), reverse=True)
                      if p.is_dir()]
        except OSError:
            continue
    return paths


def find_idf() -> tuple[list[str], dict[str, str]] | None:
    for name in ("idf.py", "idf.py.exe"):
        exe = shutil.which(name)
        if exe:
            return [exe], {}
    for idf_path in _candidate_idf_paths():
        idf_py = idf_path / "tools" / "idf.py"
        if not idf_py.is_file():
            continue
        env = {"IDF_PATH": str(idf_path)}
        python = _idf_python(idf_path) or sys.executable
        return [python, str(idf_py)], env
    return None


@dataclass
class ToolStatus:
    name: str
    group: str
    description: str
    install: str
    path: str = ""
    version: str = ""

    @property
    def found(self) -> bool:
        return bool(self.path)


def _version_line(path: str, args: list[str], timeout: float = 6.0) -> str:
    try:
        proc = subprocess.run(
            [path, *args], capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (proc.stdout or "") + (proc.stderr or "")
    for line in output.splitlines():
        line = line.strip()
        if line:
            return line[:110]
    return ""


def scan() -> list[ToolStatus]:
    idf = find_idf()
    result = []
    for name, group, args, description, install in TOOLS:
        if name == "idf.py":
            path = idf[0][-1] if idf else ""
            version = "ESP-IDF toolchain" if idf else ""
            result.append(ToolStatus(name, group, description, install, path, version))
            continue
        path = shutil.which(name) or ""
        version = _version_line(path, args) if path else ""
        result.append(ToolStatus(name, group, description, install, path, version))
    return result


def missing_for(kind: str, statuses: list[ToolStatus]) -> list[str]:
    found = {s.name for s in statuses if s.found}
    return [tool for tool in REQUIRED.get(kind, ()) if tool not in found]


def missing_for_project(project, statuses: list[ToolStatus]) -> list[str]:
    kind = project if isinstance(project, str) else project.kind
    meta = {} if isinstance(project, str) else (project.meta or {})
    if kind == "esp-idf":
        return [] if find_idf() else ["idf.py"]
    required = list(REQUIRED.get(kind, ()))
    if kind == "gradle":
        wrapper = Path(str(meta.get("wrapper") or ""))
        if wrapper.is_file():
            required = [tool for tool in required if tool != "gradle"]
    found = {s.name for s in statuses if s.found}
    return [tool for tool in required if tool not in found]
