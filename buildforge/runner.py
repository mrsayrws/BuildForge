from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .detect import Project
from .toolchains import find_idf

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CREATE_NEW_PROCESS_GROUP = 0x00000200 if os.name == "nt" else 0


@dataclass
class Step:
    label: str
    cmd: list[str] | str
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Plan:
    project: Project
    steps: list[Step] = field(default_factory=list)
    notes: str = ""
    clean_paths: list[Path] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.steps


def default_jobs() -> int:
    return max(1, min(os.cpu_count() or 4, 32))


def _wrap(cmd: list[str]) -> list[str]:
    if os.name == "nt" and cmd and cmd[0].lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", *cmd]
    return cmd


def _which(name: str) -> str:
    return shutil.which(name) or name


def _python() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or shutil.which("py") or "python"


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _quoted(paths: list[Path], root: Path) -> list[str]:
    out = []
    for p in paths:
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.as_posix()
        out.append(f'"{rel}"' if " " in rel else rel)
    return out


def _cpp_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    lang = project.meta.get("lang", "c++")
    compiler = _which("g++" if lang == "c++" else "gcc")
    std = "-std=c++20" if lang == "c++" else "-std=c17"
    out_dir = project.root / "buildforge-out"
    excluded = set(project.meta.get("other_mains", []))
    sources = [p for p in project.sources if str(p) not in excluded]
    if not sources:
        return Plan(project, notes="No source files found.")

    flags = [std, "-Wall", "-Wextra"]
    if release:
        flags += ["-O2", "-DNDEBUG"]
    else:
        flags += ["-O0", "-g"]

    steps: list[Step] = []
    if project.entry:
        out_dir.mkdir(parents=True, exist_ok=True)
        binary = out_dir / _exe(project.entry.stem or "app")
        listed = _quoted(sources, project.root)
        if len(listed) > 25:
            rsp = out_dir / "sources.rsp"
            rsp.write_text("\n".join(listed), encoding="utf-8")
            listed = [f"@{rsp.name}"]
        cmd = [compiler, *flags, "-I.", "-o", str(binary), *listed]
        steps.append(Step(f"Compile {len(sources)} file(s) → {binary.name}",
                          _wrap(cmd), project.root))
        notes = "Debug symbols included." if not release else "Optimised release build."
        if jobs > 1:
            notes += " Single translation-unit link; files compile in one g++ invocation."
    else:
        cmd = [compiler, std, "-fsyntax-only", *sources]
        steps.append(Step("Syntax check (no main detected)", _wrap(cmd), project.root))
        notes = "No main() found — checking syntax only."

    return Plan(project, steps, notes, [out_dir] if clean else [])


def _cmake_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    build_dir = Path(project.meta.get("build_dir") or (project.root / "build"))
    cfg = "Release" if release else "Debug"
    steps = []
    clean_paths = []
    if clean:
        clean_paths.append(build_dir)
    configured = (build_dir / "CMakeCache.txt").exists() and not clean
    if not configured:
        configure = [_which("cmake"), "-S", ".", "-B", str(build_dir),
                     f"-DCMAKE_BUILD_TYPE={cfg}"]
        has_msvc = shutil.which("cl") is not None
        if not has_msvc:
            if shutil.which("ninja"):
                configure += ["-G", "Ninja"]
            if shutil.which("gcc"):
                configure.append(f"-DCMAKE_C_COMPILER={_which('gcc')}")
            if shutil.which("g++"):
                configure.append(f"-DCMAKE_CXX_COMPILER={_which('g++')}")
        steps.append(Step(f"Configure ({cfg})", _wrap(configure), project.root))
    steps.append(Step(
        f"Build ({cfg}, -j{jobs})",
        _wrap([_which("cmake"), "--build", str(build_dir),
               "--parallel", str(jobs), "--config", cfg]),
        project.root,
    ))
    return Plan(project, steps, "CMake reuses the build directory; only changed files rebuild.",
                clean_paths)


def _dotnet_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    target = project.meta.get("target") or str(project.entry or project.root)
    cfg = "Release" if release else "Debug"
    steps = []
    if clean:
        steps.append(Step("dotnet clean", _wrap([_which("dotnet"), "clean", target,
                                                 "-c", cfg, "--nologo"]), project.root))
    steps.append(Step(f"dotnet build ({cfg})",
                      _wrap([_which("dotnet"), "build", target, "-c", cfg,
                             "--nologo", "-v", "minimal", "-nodeReuse:false"]),
                      project.root))
    return Plan(project, steps, "MSBuild incremental build; only changed projects rebuild.")


def _node_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    steps = []
    lock = project.meta.get("lock", "")
    has_modules = (project.root / "node_modules").exists()
    if lock.endswith("pnpm-lock.yaml") and shutil.which("pnpm"):
        installer = [_which("pnpm"), "install"]
    elif lock.endswith("yarn.lock") and shutil.which("yarn"):
        installer = [_which("yarn"), "install"]
    elif lock in ("package-lock.json", "npm-shrinkwrap.json"):
        installer = [_which("npm"), "ci", "--no-audit", "--no-fund"]
    else:
        installer = [_which("npm"), "install", "--no-audit", "--no-fund"]
    if not has_modules or clean:
        steps.append(Step("Install dependencies", _wrap(installer), project.root))
    if project.meta.get("has_build"):
        steps.append(Step("npm run build", _wrap([_which("npm"), "run", "build"]),
                          project.root))
        notes = "Runs the project's own build script."
    else:
        notes = "package.json has no build script — dependencies installed only."
    return Plan(project, steps, notes)


def _python_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    cmd = [_python(), "-m", "compileall", "-q",
           "-x", r"(\.venv|venv|env|node_modules|build|dist|\.git|__pycache__)", "."]
    return Plan(project, [Step("Compile all Python sources", _wrap(cmd), project.root)],
                "Fast syntax + bytecode validation without running the code.")


def _rust_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    steps = []
    if clean:
        steps.append(Step("cargo clean", _wrap([_which("cargo"), "clean"]), project.root))
    cmd = [_which("cargo"), "build"]
    if release:
        cmd.append("--release")
    steps.append(Step(f"cargo build ({'release' if release else 'debug'})",
                      _wrap(cmd), project.root))
    return Plan(project, steps, "Cargo keeps incremental artefacts in target/.")


def _go_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    cmd = [_which("go"), "build", "./..."]
    steps = [Step("go build ./...", _wrap(cmd), project.root)]
    return Plan(project, steps, "The Go build cache is shared across projects.")


def _maven_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    cmd = [_which("mvn"), "-q", "-DskipTests", "package"]
    steps = []
    if clean:
        cmd = [_which("mvn"), "-q", "clean", "package", "-DskipTests"]
    steps.append(Step("Maven package (tests skipped)", _wrap(cmd), project.root))
    return Plan(project, steps, "Skips tests for a fast build; run mvn test separately.")


def _gradle_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    wrapper = Path(project.meta.get("wrapper", ""))
    gradle = str(wrapper) if wrapper.is_file() else _which("gradle")
    cmd = [gradle, "build", "--console=plain", f"--max-workers={jobs}"]
    if clean:
        cmd.append("--rerun-tasks")
    return Plan(project, [Step("Gradle build", _wrap(cmd), project.root)],
                "Gradle daemon and build cache are reused between runs.")


def _make_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    make = _which("make")
    cmd = [make, f"-j{jobs}"]
    steps = []
    if clean:
        steps.append(Step("make clean", _wrap([make, "clean"]), project.root))
    steps.append(Step(f"make -j{jobs}", _wrap(cmd), project.root))
    return Plan(project, steps, "Incremental by timestamps.")


def _msvc_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    target = project.meta.get("target") or str(project.entry)
    cfg = "Release" if release else "Debug"
    cmd = [_which("msbuild"), target, f"/p:Configuration={cfg}",
           f"/m:{jobs}", "/nologo", "/v:minimal"]
    steps = [Step(f"MSBuild ({cfg})", _wrap(cmd), project.root)]
    return Plan(project, steps,
                "MSBuild needs Visual Studio Build Tools; if missing, install them from Toolchains.")


def _idf_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    info = find_idf()
    if info is None:
        return Plan(project, notes=(
            "ESP-IDF firmware detected, but idf.py was not found. Install ESP-IDF "
            "(winget install --id Espressif.EIM-CLI, then run: eim install) and open a "
            "new shell, or build from the ESP-IDF command prompt."))
    base, idf_env = info
    cfg = "Release" if release else "Debug"
    target = project.meta.get("target") or "esp32"
    env = dict(idf_env)
    env["IDF_TARGET"] = target

    build_dir = project.root / "build"
    cache = build_dir / "CMakeCache.txt"
    foreign = False
    try:
        foreign = cache.is_file() and "idf_path" not in cache.read_text(
            encoding="utf-8", errors="ignore").lower()
    except OSError:
        pass
    # A cache without IDF_PATH was left by a plain CMake attempt; ESP-IDF cannot
    # reuse it, so build elsewhere and leave the old folder untouched.
    use_dir = project.root / "buildforge-out" if foreign else build_dir
    cmd = [*base, "-B", str(use_dir), "-j", str(jobs),
           f"-DCMAKE_BUILD_TYPE={cfg}", "build"]
    steps = [Step(f"idf.py build ({cfg}, {target})", cmd, project.root, env)]
    notes = "ESP-IDF configures and builds incrementally."
    if foreign:
        notes += " Stale non-ESP-IDF cache found — building into buildforge-out/."
    clean_paths = [use_dir] if clean else []
    return Plan(project, steps, notes, clean_paths)


def _platformio_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    pio = _which("pio")
    steps = []
    if clean:
        steps.append(Step("pio run -t clean", _wrap([pio, "run", "-t", "clean"]),
                          project.root))
    steps.append(Step("pio run", _wrap([pio, "run", "-j", str(jobs)]), project.root))
    return Plan(project, steps, "PlatformIO builds every environment declared in platformio.ini.")


def _meson_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    build_dir = project.root / "build"
    buildtype = "release" if release else "debug"
    steps = []
    if not (build_dir / "build.ninja").exists() or clean:
        steps.append(Step(f"meson setup ({buildtype})",
                          _wrap([_which("meson"), "setup", str(build_dir),
                                 f"--buildtype={buildtype}"]), project.root))
    steps.append(Step(f"meson compile (-j{jobs})",
                      _wrap([_which("meson"), "compile", "-C", str(build_dir),
                             "-j", str(jobs)]), project.root))
    return Plan(project, steps, "Ninja inside Meson only rebuilds changed files.",
                [build_dir] if clean else [])


def _bazel_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    bazel = _which("bazel")
    steps = []
    if clean:
        steps.append(Step("bazel clean", _wrap([bazel, "clean"]), project.root))
    steps.append(Step("bazel build //...",
                      _wrap([bazel, "build", "//...", f"--jobs={jobs}"]), project.root))
    return Plan(project, steps, "Bazel reuses its analysis and action caches.")


def _qmake_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    target = project.meta.get("target") or str(project.entry or ".")
    steps = []
    if clean:
        steps.append(Step("make clean", _wrap([_which("make"), "clean"]), project.root))
    steps.append(Step("qmake", _wrap([_which("qmake"), target]), project.root))
    steps.append(Step(f"make -j{jobs}", _wrap([_which("make"), f"-j{jobs}"]),
                      project.root))
    return Plan(project, steps, "qmake regenerates the Makefile from the .pro file.")


def _arduino_plan(project: Project, release: bool, jobs: int, clean: bool) -> Plan:
    fqbn = str(project.meta.get("fqbn") or "")
    if not fqbn:
        return Plan(project, notes=(
            "Arduino sketch detected, but no board FQBN is known. Add a sketch.yaml "
            "with default_fqbn, or set a custom command: "
            "arduino-cli compile --fqbn <vendor:arch:board> ."))
    out_dir = project.root / "buildforge-out"
    cmd = [_which("arduino-cli"), "compile", "--fqbn", fqbn,
           "--build-path", str(out_dir), "."]
    return Plan(project, [Step(f"arduino-cli compile ({fqbn})", _wrap(cmd),
                               project.root)],
                "Arduino CLI builds the sketch for the configured board.",
                [out_dir] if clean else [])


def _custom_plan(project: Project, command: str) -> Plan:
    if os.name == "nt":
        # A raw command line is passed through untouched; list2cmdline would
        # escape embedded quotes and cmd.exe would hand them to the child.
        cmd: list[str] | str = f"cmd /d /s /c {command}"
    else:
        cmd = ["sh", "-c", command]
    return Plan(project, [Step("Custom command", cmd, project.root)],
                "Custom command from project settings.")


def make_plan(project: Project, release: bool = True, jobs: int | None = None,
              clean: bool = False, custom: str = "") -> Plan:
    jobs = jobs or default_jobs()
    builders = {
        "cpp": _cpp_plan, "c": _cpp_plan, "cmake": _cmake_plan,
        "dotnet": _dotnet_plan, "node": _node_plan, "python": _python_plan,
        "rust": _rust_plan, "go": _go_plan, "maven": _maven_plan,
        "gradle": _gradle_plan, "make": _make_plan, "msvc": _msvc_plan,
        "esp-idf": _idf_plan, "platformio": _platformio_plan,
        "meson": _meson_plan, "bazel": _bazel_plan, "qmake": _qmake_plan,
        "arduino": _arduino_plan,
    }
    if project.kind in builders:
        return builders[project.kind](project, release, jobs, clean)
    if custom.strip():
        return _custom_plan(project, custom.strip())
    return Plan(project, notes="No build system detected. Set a custom command in Settings.")


def command_line(step: Step) -> str:
    if isinstance(step.cmd, str):
        return step.cmd
    return subprocess.list2cmdline(step.cmd)


class BuildRunner:
    def __init__(self, emit, timeout_seconds: int = 0):
        self.emit = emit
        self.timeout_seconds = timeout_seconds
        self._proc: subprocess.Popen | None = None
        self._cancelled = False
        self._timer: threading.Timer | None = None

    def cancel(self) -> None:
        self._cancelled = True
        proc = self._proc
        if proc and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            else:
                proc.terminate()
        self._stop_timer()

    def _stop_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _on_timeout(self) -> None:
        self.emit({"type": "line", "text": "build timed out — stopping", "tag": "err"})
        self.cancel()

    def run(self, plan: Plan) -> bool:
        started = time.perf_counter()
        self._cancelled = False
        for path in plan.clean_paths:
            shutil.rmtree(path, ignore_errors=True)

        for index, step in enumerate(plan.steps, 1):
            if self._cancelled:
                break
            self.emit({"type": "step", "index": index, "total": len(plan.steps),
                       "label": step.label})
            self.emit({"type": "line", "text": f"$ {command_line(step)}", "tag": "dim"})
            env = os.environ.copy()
            env.update({
                "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",
                "CARGO_TERM_COLOR": "never", "NO_COLOR": "1", "CLICOLOR": "0",
                "FORCE_COLOR": "0", "GIT_TERMINAL_PROMPT": "0",
                "MSBUILDTERMINALLOGGER": "off", "CMAKE_COLOR_DIAGNOSTICS": "OFF",
            })
            if step.env:
                env.update(step.env)
            try:
                self._proc = subprocess.Popen(
                    step.cmd, cwd=str(step.cwd), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                )
            except (OSError, ValueError) as exc:
                self.emit({"type": "line", "text": f"cannot start: {exc}", "tag": "err"})
                self.emit({"type": "done", "ok": False, "seconds": time.perf_counter() - started,
                           "code": -1, "cancelled": self._cancelled})
                return False

            if self.timeout_seconds:
                self._timer = threading.Timer(self.timeout_seconds, self._on_timeout)
                self._timer.daemon = True
                self._timer.start()

            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                self.emit({"type": "line", "text": line.rstrip("\r\n")})
            code = self._proc.wait()
            self._stop_timer()

            if self._cancelled:
                break
            if code != 0:
                self.emit({"type": "line",
                           "text": f"step failed with exit code {code}", "tag": "err"})
                self.emit({"type": "done", "ok": False,
                           "seconds": time.perf_counter() - started,
                           "code": code, "cancelled": False})
                return False

        self.emit({"type": "done", "ok": not self._cancelled,
                   "seconds": time.perf_counter() - started,
                   "code": 0, "cancelled": self._cancelled})
        return not self._cancelled
