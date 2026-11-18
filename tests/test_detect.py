from pathlib import Path

import pytest

from buildforge.detect import KIND_DESCRIPTIONS, detect_project


def write(root: Path, name: str, text: str = "") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_rust(tmp_path):
    write(tmp_path, "Cargo.toml", "[package]\nname='x'")
    project = detect_project(tmp_path)
    assert project.kind == "rust"
    assert project.root == tmp_path.resolve()


def test_go(tmp_path):
    write(tmp_path, "go.mod", "module example.com/x\n")
    assert detect_project(tmp_path).kind == "go"


def test_cmake_prefers_manifest(tmp_path):
    write(tmp_path, "CMakeLists.txt", "cmake_minimum_required(VERSION 3.20)\n")
    write(tmp_path, "main.cpp", "int main() { return 0; }")
    project = detect_project(tmp_path)
    assert project.kind == "cmake"
    assert project.meta["build_dir"].endswith("build")


def test_node_scripts(tmp_path):
    write(tmp_path, "package.json",
          '{"scripts": {"build": "vite build", "test": "vitest"}}')
    write(tmp_path, "package-lock.json", "{}")
    project = detect_project(tmp_path)
    assert project.kind == "node"
    assert project.meta["has_build"] is True
    assert project.meta["lock"] == "package-lock.json"


def test_python(tmp_path):
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    assert detect_project(tmp_path).kind == "python"


def test_dotnet_solution_and_project(tmp_path):
    write(tmp_path, "App.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\" />")
    project = detect_project(tmp_path)
    assert project.kind == "dotnet"
    assert project.entry.name == "App.csproj"

    write(tmp_path, "All.sln", "Microsoft Visual Studio Solution File")
    solution = detect_project(tmp_path)
    assert solution.kind == "dotnet"
    assert solution.entry.name == "All.sln"


def test_dotnet_nested_csproj(tmp_path):
    write(tmp_path, "src/Deep/App.csproj", "<Project />")
    project = detect_project(tmp_path)
    assert project.kind == "dotnet"
    assert project.entry.name == "App.csproj"


def test_makefile(tmp_path):
    write(tmp_path, "Makefile", "all:\n\techo hi\n")
    assert detect_project(tmp_path).kind == "make"


def test_cpp_main_detection(tmp_path):
    write(tmp_path, "src/main.cpp", "int main() { return 0; }\n")
    write(tmp_path, "src/helper.cpp", "int helper() { return 1; }\n")
    write(tmp_path, "src/other_main.cpp",
          "auto main() -> int { return 0; }\n")
    project = detect_project(tmp_path)
    assert project.kind == "cpp"
    assert project.entry == tmp_path / "src" / "main.cpp"
    assert len(project.sources) == 3
    assert len(project.meta["other_mains"]) == 1


def test_c_only(tmp_path):
    write(tmp_path, "main.c", "int main(void) { return 0; }\n")
    project = detect_project(tmp_path)
    assert project.kind == "c"
    assert project.meta["lang"] == "c"


def test_skips_dependency_folders(tmp_path):
    write(tmp_path, "node_modules/pkg/main.cpp", "int main() { return 0; }\n")
    write(tmp_path, "vendor/lib.cpp", "int lib() { return 0; }\n")
    project = detect_project(tmp_path)
    assert project.kind == "unknown"
    assert KIND_DESCRIPTIONS["unknown"]


def test_esp_idf_from_cmake_and_sdkconfig(tmp_path, monkeypatch):
    monkeypatch.delenv("IDF_TARGET", raising=False)
    write(tmp_path, "CMakeLists.txt",
          'include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n'
          "project(firmware)\n")
    write(tmp_path, "sdkconfig.defaults", 'CONFIG_IDF_TARGET="esp32s3"\n')
    project = detect_project(tmp_path)
    assert project.kind == "esp-idf"
    assert project.meta["target"] == "esp32s3"


def test_esp_idf_from_component_register(tmp_path):
    write(tmp_path, "main/CMakeLists.txt",
          'idf_component_register(SRCS "main.c")\n')
    assert detect_project(tmp_path).kind == "esp-idf"


def test_platformio(tmp_path):
    write(tmp_path, "platformio.ini", "[env:esp32dev]\nplatform = espressif32\n")
    assert detect_project(tmp_path).kind == "platformio"


def test_meson(tmp_path):
    write(tmp_path, "meson.build", "project('x', 'c')\n")
    assert detect_project(tmp_path).kind == "meson"


def test_bazel(tmp_path):
    write(tmp_path, "MODULE.bazel", "")
    assert detect_project(tmp_path).kind == "bazel"
    (tmp_path / "MODULE.bazel").unlink()
    write(tmp_path, "WORKSPACE", "")
    assert detect_project(tmp_path).kind == "bazel"


def test_qmake(tmp_path):
    write(tmp_path, "app.pro", "SOURCES += main.cpp\n")
    assert detect_project(tmp_path).kind == "qmake"


def test_arduino_sketch_with_board(tmp_path):
    write(tmp_path, "blink.ino", "void setup() {}\nvoid loop() {}\n")
    write(tmp_path, "sketch.yaml", "default_fqbn: esp32:esp32:esp32\n")
    project = detect_project(tmp_path)
    assert project.kind == "arduino"
    assert project.meta["fqbn"] == "esp32:esp32:esp32"


def test_python_scripts_without_manifest(tmp_path):
    write(tmp_path, "tool.py", "print('hi')\n")
    fields = tmp_path / "scripts"
    write(fields, "job.py", "print('job')\n")
    project = detect_project(tmp_path)
    assert project.kind == "python"
    assert project.meta["scripts"] == 2


def test_nested_project_is_found(tmp_path):
    write(tmp_path / "real", "Cargo.toml", "[package]\nname='x'")
    project = detect_project(tmp_path)
    assert project.kind == "rust"
    assert project.root == (tmp_path / "real").resolve()
    assert project.meta["via"] == tmp_path.name


def test_ambiguous_nested_folders_stay_unknown(tmp_path):
    write(tmp_path / "a", "Cargo.toml", "[package]\nname='a'")
    write(tmp_path / "b", "go.mod", "module b\n")
    assert detect_project(tmp_path).kind == "unknown"


def test_missing_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        detect_project(tmp_path / "nope")
