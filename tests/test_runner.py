import sys
from pathlib import Path

from buildforge.detect import detect_project
from buildforge.runner import (BuildRunner, Plan, Step, command_line, default_jobs,
                               make_plan)


def write(root: Path, name: str, text: str = "") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_default_jobs_range():
    jobs = default_jobs()
    assert 1 <= jobs <= 32


def test_cpp_plan_is_one_compile_step(tmp_path):
    write(tmp_path, "main.cpp", "#include <iostream>\nint main(){return 0;}\n")
    project = detect_project(tmp_path)
    plan = make_plan(project, release=True, jobs=4)
    assert not plan.empty
    step = plan.steps[0]
    assert "g++" in Path(step.cmd[0]).name
    assert "-std=c++20" in step.cmd
    assert "-O2" in step.cmd
    assert any(part.endswith("main") or part.endswith("main.exe")
               for part in step.cmd)


def test_cpp_debug_flags(tmp_path):
    write(tmp_path, "main.cpp", "int main(){return 0;}\n")
    plan = make_plan(detect_project(tmp_path), release=False)
    assert "-O0" in plan.steps[0].cmd and "-g" in plan.steps[0].cmd


def test_cpp_without_main_checks_syntax(tmp_path):
    write(tmp_path, "lib.cpp", "int f(){return 1;}\n")
    plan = make_plan(detect_project(tmp_path))
    assert "-fsyntax-only" in plan.steps[0].cmd


def test_cmake_plan_configures_once(tmp_path):
    write(tmp_path, "CMakeLists.txt", "project(x)\n")
    project = detect_project(tmp_path)
    plan = make_plan(project, jobs=3)
    labels = [s.label for s in plan.steps]
    assert any(label.startswith("Configure") for label in labels)
    build = [s for s in plan.steps if s.label.startswith("Build")][0]
    assert "--parallel" in build.cmd and "3" in build.cmd


def test_cmake_plan_skips_configure_when_cached(tmp_path):
    write(tmp_path, "CMakeLists.txt", "project(x)\n")
    write(tmp_path, "build/CMakeCache.txt", "")
    plan = make_plan(detect_project(tmp_path))
    assert len(plan.steps) == 1


def test_cmake_clean_removes_build_dir(tmp_path):
    write(tmp_path, "CMakeLists.txt", "project(x)\n")
    plan = make_plan(detect_project(tmp_path), clean=True)
    assert plan.clean_paths == [tmp_path.resolve() / "build"]
    assert any(s.label.startswith("Configure") for s in plan.steps)


def test_dotnet_debug_plan(tmp_path):
    write(tmp_path, "App.csproj", "<Project />")
    plan = make_plan(detect_project(tmp_path), release=False, clean=True)
    labels = [s.label for s in plan.steps]
    assert labels == ["dotnet clean", "dotnet build (Debug)"]


def test_node_installs_once_then_builds(tmp_path):
    write(tmp_path, "package.json", '{"scripts": {"build": "vite build"}}')
    plan = make_plan(detect_project(tmp_path))
    assert [s.label for s in plan.steps] == ["Install dependencies", "npm run build"]

    (tmp_path / "node_modules").mkdir()
    plan = make_plan(detect_project(tmp_path))
    assert [s.label for s in plan.steps] == ["npm run build"]


def test_node_npm_ci_with_lockfile(tmp_path):
    write(tmp_path, "package.json", '{"scripts": {}}')
    write(tmp_path, "package-lock.json", "{}")
    plan = make_plan(detect_project(tmp_path))
    assert "ci" in plan.steps[0].cmd


def test_python_plan_compiles(tmp_path):
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    plan = make_plan(detect_project(tmp_path))
    assert "compileall" in plan.steps[0].cmd


def test_rust_release(tmp_path):
    write(tmp_path, "Cargo.toml", "[package]\nname='x'")
    plan = make_plan(detect_project(tmp_path), release=True, clean=True)
    assert [s.label for s in plan.steps] == ["cargo clean", "cargo build (release)"]


def test_go_plan(tmp_path):
    write(tmp_path, "go.mod", "module x\n")
    plan = make_plan(detect_project(tmp_path))
    assert plan.steps[0].cmd[-1] == "./..."


def test_make_plan_clean(tmp_path):
    write(tmp_path, "Makefile", "all:\n")
    plan = make_plan(detect_project(tmp_path), jobs=2, clean=True)
    assert [s.label for s in plan.steps] == ["make clean", "make -j2"]


def test_unknown_uses_custom_command(tmp_path):
    project = detect_project(tmp_path)
    assert project.kind == "unknown"
    empty = make_plan(project)
    assert empty.empty and "custom command" in empty.notes.lower()
    plan = make_plan(project, custom="echo hi")
    assert plan.steps[0].label == "Custom command"


def test_command_line_quotes_spaces():
    step = Step("x", ["tool.exe", "a b"], Path("."))
    assert '"a b"' in command_line(step)


def test_runner_streams_lines_and_reports_success(tmp_path):
    events = []
    plan = Plan(detect_project(tmp_path), [
        Step("hello", [sys.executable, "-c", "print('hello forge')"], tmp_path),
    ])
    ok = BuildRunner(events.append).run(plan)
    assert ok
    lines = [e["text"] for e in events if e["type"] == "line"]
    assert "hello forge" in lines
    done = [e for e in events if e["type"] == "done"][0]
    assert done["ok"] is True and done["code"] == 0


def test_runner_reports_failure_code(tmp_path):
    events = []
    plan = Plan(detect_project(tmp_path), [
        Step("fail", [sys.executable, "-c", "raise SystemExit(3)"], tmp_path),
    ])
    ok = BuildRunner(events.append).run(plan)
    done = [e for e in events if e["type"] == "done"][0]
    assert ok is False
    assert done["ok"] is False and done["code"] == 3


def test_runner_missing_binary_is_graceful(tmp_path):
    events = []
    plan = Plan(detect_project(tmp_path), [
        Step("nope", ["definitely-not-a-real-binary-xyz"], tmp_path),
    ])
    assert BuildRunner(events.append).run(plan) is False
    text = " ".join(e.get("text", "") for e in events)
    assert "cannot start" in text


def test_cmake_plan_uses_local_compilers(tmp_path):
    import shutil as _shutil

    write(tmp_path, "CMakeLists.txt", "project(x)\n")
    plan = make_plan(detect_project(tmp_path))
    configure = plan.steps[0].cmd
    if _shutil.which("cl") is None and _shutil.which("g++"):
        assert any(part.startswith("-DCMAKE_CXX_COMPILER=") for part in configure)
    if _shutil.which("cl") is None and _shutil.which("ninja"):
        assert "Ninja" in configure


def test_esp_idf_plan_requires_toolchain(tmp_path, monkeypatch):
    import buildforge.runner as runner

    monkeypatch.setattr(runner, "find_idf", lambda: None)
    write(tmp_path, "sdkconfig", "")
    write(tmp_path, "CMakeLists.txt",
          'include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n')
    project = detect_project(tmp_path)
    assert project.kind == "esp-idf"
    plan = make_plan(project)
    assert plan.empty
    assert "idf.py" in plan.notes


def test_esp_idf_plan_uses_target_and_env(tmp_path, monkeypatch):
    import buildforge.runner as runner

    monkeypatch.delenv("IDF_TARGET", raising=False)
    idf_py = tmp_path / "idf" / "tools" / "idf.py"
    idf_py.parent.mkdir(parents=True)
    idf_py.write_text("print('fake')\n", encoding="utf-8")
    monkeypatch.setattr(runner, "find_idf",
                        lambda: ([sys.executable, str(idf_py)],
                                 {"IDF_PATH": str(idf_py.parent.parent)}))
    write(tmp_path, "sdkconfig", 'CONFIG_IDF_TARGET="esp32c3"\n')
    write(tmp_path, "CMakeLists.txt",
          'include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n')
    plan = make_plan(detect_project(tmp_path), release=False, jobs=3, clean=True)
    step = plan.steps[0]
    assert step.cmd[-1] == "build"
    assert step.cmd[0] == sys.executable
    assert step.env["IDF_TARGET"] == "esp32c3"
    assert "Debug" in step.label
    assert plan.clean_paths == [tmp_path.resolve() / "build"]


def test_platformio_plan(tmp_path):
    write(tmp_path, "platformio.ini", "[env:esp32dev]\n")
    plan = make_plan(detect_project(tmp_path), jobs=4, clean=True)
    assert [s.label for s in plan.steps] == ["pio run -t clean", "pio run"]
    assert "-j" in plan.steps[1].cmd


def test_meson_plan_and_incremental(tmp_path):
    write(tmp_path, "meson.build", "project('x')\n")
    plan = make_plan(detect_project(tmp_path), jobs=4)
    assert [s.label for s in plan.steps] == ["meson setup (release)", "meson compile (-j4)"]
    write(tmp_path, "build/build.ninja", "")
    plan = make_plan(detect_project(tmp_path), jobs=4)
    assert len(plan.steps) == 1 and "compile" in plan.steps[0].label


def test_bazel_plan_clean(tmp_path):
    write(tmp_path, "WORKSPACE", "")
    plan = make_plan(detect_project(tmp_path), jobs=2, clean=True)
    assert [s.label for s in plan.steps] == ["bazel clean", "bazel build //..."]


def test_arduino_plan_needs_fqbn(tmp_path):
    write(tmp_path, "blink.ino", "void setup() {}\nvoid loop() {}\n")
    project = detect_project(tmp_path)
    plan = make_plan(project)
    assert plan.empty and "FQBN" in plan.notes
    write(tmp_path, "sketch.yaml", "default_fqbn: esp32:esp32:esp32\n")
    plan = make_plan(detect_project(tmp_path))
    assert not plan.empty and "--fqbn" in plan.steps[0].cmd


def test_esp_idf_avoids_foreign_cmake_cache(tmp_path, monkeypatch):
    import buildforge.runner as runner

    idf_py = tmp_path / "idf" / "tools" / "idf.py"
    idf_py.parent.mkdir(parents=True)
    idf_py.write_text("print('fake')\n", encoding="utf-8")
    monkeypatch.setattr(runner, "find_idf",
                        lambda: ([sys.executable, str(idf_py)], {}))
    write(tmp_path, "sdkconfig", "")
    write(tmp_path, "CMakeLists.txt",
          'include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n')
    write(tmp_path, "build/CMakeCache.txt", "CMAKE_GENERATOR:INTERNAL=NMake Makefiles\n")
    plan = make_plan(detect_project(tmp_path))
    command = " ".join(plan.steps[0].cmd)
    assert "buildforge-out" in command
    assert "Stale" in plan.notes
    assert plan.clean_paths == []


def test_esp_idf_real_cli_build(tmp_path, monkeypatch):
    import buildforge.runner as runner

    idf_py = tmp_path / "idf" / "tools" / "idf.py"
    idf_py.parent.mkdir(parents=True)
    idf_py.write_text(
        "import os\n"
        "os.makedirs('build', exist_ok=True)\n"
        "open('build/fw.bin','w').write(os.environ['IDF_TARGET'])\n",
        encoding="utf-8")
    monkeypatch.setattr(runner, "find_idf",
                        lambda: ([sys.executable, str(idf_py)],
                                 {"IDF_PATH": str(idf_py.parent.parent)}))
    write(tmp_path, "sdkconfig", 'CONFIG_IDF_TARGET="esp32"\n')
    write(tmp_path, "CMakeLists.txt",
          'include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n')
    project = detect_project(tmp_path)
    events = []
    assert BuildRunner(events.append).run(make_plan(project, jobs=2))
    assert (tmp_path / "build" / "fw.bin").read_text() == "esp32"
