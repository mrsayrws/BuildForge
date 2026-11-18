from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    "build", "dist", "target", ".buildforge", ".idea", ".vs", "bin", "obj",
    ".pytest_cache", ".mypy_cache", "packages", "vendor", "coverage",
}

CPP_EXTS = {".cpp", ".cc", ".cxx", ".c++"}
C_EXTS = {".c"}

MAIN_RE = re.compile(r"\b(?:int|void|auto)\s+main\s*\(", re.MULTILINE)
IDF_INCLUDE_RE = re.compile(r"(?:\$ENV\{IDF_PATH\}|esp-idf)[^\"']*project\.cmake",
                            re.IGNORECASE)
IDF_TARGET_RE = re.compile(r'^\s*CONFIG_IDF_TARGET="?([A-Za-z0-9_]+)"?', re.MULTILINE)
ARDUINO_FQBN_RE = re.compile(r"^\s*default_fqbn:\s*(\S+)", re.MULTILINE)


@dataclass
class Project:
    root: Path
    kind: str
    label: str
    entry: Path | None = None
    sources: list[Path] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.root.name or str(self.root)


def walk_files(root: Path, max_depth: int = 6):
    root = Path(root)
    base = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.parts) - base
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".buildforge")
        )
        if depth >= max_depth:
            dirnames[:] = []
        for name in sorted(filenames):
            yield current / name


def _root_files(root: Path) -> list[Path]:
    try:
        return [p for p in root.iterdir() if p.is_file()]
    except OSError:
        return []


def _first(files: list[Path], *names: str) -> Path | None:
    lowered = {p.name.lower(): p for p in files}
    for name in names:
        hit = lowered.get(name.lower())
        if hit:
            return hit
    return None


def _has_main(path: Path) -> bool:
    try:
        if path.stat().st_size > 512 * 1024:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(MAIN_RE.search(text))


def _pick_cpp_entry(mains: list[Path], root: Path) -> Path | None:
    if not mains:
        return None

    def score(path: Path):
        rel = path.relative_to(root).as_posix().lower()
        preferred = 0 if rel in ("main.cpp", "main.cc", "main.c", "src/main.cpp",
                                 "src/main.cc", "src/main.c") else 1
        return (preferred, rel.count("/"), len(rel), rel)

    return sorted(mains, key=score)[0]


def _text_of(path: Path | None, limit: int = 512 * 1024) -> str:
    if path is None:
        return ""
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _is_esp_idf(root: Path, names: set[str], root_files: list[Path]) -> bool:
    if names & {"sdkconfig", "sdkconfig.defaults", "idf_component.yml"}:
        return True
    cmake = _first(root_files, "CMakeLists.txt")
    text = _text_of(cmake)
    if text and (IDF_INCLUDE_RE.search(text) or "idf_component_register" in text):
        return True
    for folder in ("main", "components", "src"):
        base = root / folder
        if not base.is_dir():
            continue
        candidates = [base / "CMakeLists.txt", *sorted(base.glob("*/CMakeLists.txt"))]
        for candidate in candidates[:40]:
            if "idf_component_register" in _text_of(candidate, 64 * 1024):
                return True
    return False


def _esp_idf_target(root: Path) -> str:
    import os as _os

    value = (_os.environ.get("IDF_TARGET") or "").strip()
    if value:
        return value.lower()
    for name in ("sdkconfig", "sdkconfig.defaults"):
        match = IDF_TARGET_RE.search(_text_of(root / name))
        if match:
            return match.group(1).lower()
    return "esp32"


def _arduino_fqbn(root: Path) -> str:
    match = ARDUINO_FQBN_RE.search(_text_of(root / "sketch.yaml"))
    if match:
        return match.group(1)
    try:
        import json

        data = json.loads((root / "sketch.json").read_text(encoding="utf-8"))
        return str((data.get("cpu") or {}).get("fqbn") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _detect(root: Path) -> Project:
    root_files = _root_files(root)
    names = {p.name.lower() for p in root_files}

    if "cargo.toml" in names:
        return Project(root, "rust", "Rust / Cargo", meta={"manifest": "Cargo.toml"})
    if "go.mod" in names:
        return Project(root, "go", "Go module", meta={"manifest": "go.mod"})
    if "platformio.ini" in names:
        return Project(root, "platformio", "PlatformIO",
                       meta={"manifest": "platformio.ini"})
    if _is_esp_idf(root, names, root_files):
        return Project(root, "esp-idf", "ESP-IDF firmware",
                       meta={"target": _esp_idf_target(root)})
    if "cmakelists.txt" in names:
        build = root / "build"
        return Project(root, "cmake", "CMake project", meta={
            "build_dir": str(build),
            "configured": (build / "CMakeCache.txt").exists(),
        })
    if "pom.xml" in names:
        return Project(root, "maven", "Java / Maven", meta={"manifest": "pom.xml"})
    if "build.gradle" in names or "build.gradle.kts" in names:
        wrapper = root / ("gradlew.bat" if os.name == "nt" else "gradlew")
        return Project(root, "gradle", "Java / Gradle", meta={"wrapper": str(wrapper)})
    if "package.json" in names:
        import json

        has_build = False
        scripts = {}
        try:
            data = json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = data.get("scripts") or {}
            has_build = "build" in scripts
        except (OSError, ValueError):
            pass
        lock = _first(root_files, "package-lock.json", "npm-shrinkwrap.json",
                      "pnpm-lock.yaml", "yarn.lock")
        return Project(root, "node", "Node / npm", meta={
            "has_build": has_build,
            "lock": lock.name if lock else "",
            "scripts": list(scripts),
        })
    if names & {"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"}:
        return Project(root, "python", "Python package", meta={
            "pyproject": "pyproject.toml" in names,
        })

    sln = [p for p in root_files if p.suffix.lower() == ".sln"]
    if sln:
        target = sorted(sln, key=lambda p: len(p.name))[0]
        return Project(root, "dotnet", ".NET solution", entry=target, meta={"target": str(target)})
    csproj = [p for p in root_files if p.suffix.lower() == ".csproj"]
    if not csproj:
        csproj = [p for p in walk_files(root, 4) if p.suffix.lower() == ".csproj"]
    if csproj:
        target = sorted(csproj, key=lambda p: (len(p.parts), len(p.name)))[0]
        return Project(root, "dotnet", ".NET project", entry=target, meta={"target": str(target)})

    vcxproj = [p for p in walk_files(root, 4) if p.suffix.lower() == ".vcxproj"]
    if vcxproj:
        target = sorted(vcxproj, key=lambda p: (len(p.parts), len(p.name)))[0]
        return Project(root, "msvc", "MSVC project", entry=target, meta={"target": str(target)})

    if "meson.build" in names:
        return Project(root, "meson", "Meson / Ninja", meta={"manifest": "meson.build"})
    if names & {"module.bazel", "workspace", "workspace.bazel"}:
        return Project(root, "bazel", "Bazel workspace")
    pro = [p for p in root_files if p.suffix.lower() == ".pro"]
    if pro:
        target = sorted(pro, key=lambda p: len(p.name))[0]
        return Project(root, "qmake", "Qt / qmake", entry=target, meta={"target": str(target)})
    if names & {"makefile", "gnumakefile"}:
        return Project(root, "make", "Makefile", meta={"file": "Makefile"})

    sketches = [p for p in walk_files(root, 3) if p.suffix.lower() == ".ino"]
    if sketches:
        return Project(root, "arduino", "Arduino sketch", entry=sketches[0],
                       meta={"fqbn": _arduino_fqbn(root)})

    sources = [p for p in walk_files(root, 6)
               if p.suffix.lower() in CPP_EXTS | C_EXTS]
    if sources:
        mains = [p for p in sources if _has_main(p)]
        entry = _pick_cpp_entry(mains, root)
        others = [str(p) for p in mains if p != entry]
        lang = "c" if all(p.suffix.lower() in C_EXTS for p in sources) else "c++"
        return Project(root, "c" if lang == "c" else "cpp",
                       "C / GCC" if lang == "c" else "C++ / GCC",
                       entry=entry, sources=sources,
                       meta={"other_mains": others, "lang": lang})

    scripts = [p for p in walk_files(root, 5) if p.suffix.lower() == ".py"]
    if scripts:
        return Project(root, "python", "Python scripts",
                       meta={"pyproject": False, "scripts": len(scripts)})

    return Project(root, "unknown", "Unknown project")


def _nested_project(root: Path) -> Project | None:
    try:
        children = [p for p in root.iterdir()
                    if p.is_dir() and p.name not in SKIP_DIRS
                    and not p.name.startswith(".")]
    except OSError:
        return None
    candidates = []
    for child in sorted(children):
        found = _detect(child)
        if found.kind != "unknown":
            found.meta["via"] = root.name
            candidates.append(found)
    return candidates[0] if len(candidates) == 1 else None


def detect_project(path: str | Path) -> Project:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    project = _detect(root)
    if project.kind != "unknown":
        return project
    return _nested_project(root) or project


KIND_DESCRIPTIONS = {
    "cmake": "CMake configure + build (incremental)",
    "dotnet": "dotnet build (MSBuild, incremental)",
    "node": "npm install/ci + npm run build",
    "python": "compileall syntax + bytecode check",
    "rust": "cargo build (incremental)",
    "go": "go build ./...",
    "maven": "mvn package (skips tests)",
    "gradle": "gradle build",
    "make": "make -j",
    "cpp": "g++ direct build with -std=c++20",
    "c": "gcc direct build with -std=c17",
    "msvc": "MSBuild Release (needs Visual Studio Build Tools)",
    "esp-idf": "ESP-IDF firmware — idf.py build (needs the ESP-IDF toolchain)",
    "platformio": "PlatformIO — pio run",
    "meson": "Meson setup + Ninja compile",
    "bazel": "bazel build //...",
    "qmake": "Qt qmake + make",
    "arduino": "Arduino sketch — arduino-cli compile (needs a board FQBN)",
    "unknown": "No build system detected — set a custom command",
}
