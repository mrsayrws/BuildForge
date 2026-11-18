import sys
from pathlib import Path

import buildforge.toolchains as tc


def _fake_idf(tmp_path: Path) -> Path:
    idf = tmp_path / "idf"
    tools = idf / "tools"
    tools.mkdir(parents=True)
    (tools / "idf.py").write_text("print('idf')\n", encoding="utf-8")
    return idf


def test_find_idf_from_env(tmp_path, monkeypatch):
    idf = _fake_idf(tmp_path)
    monkeypatch.setenv("IDF_PATH", str(idf))
    monkeypatch.setenv("IDF_TOOLS_PATH", str(tmp_path / "no-tools"))
    monkeypatch.setattr(tc, "_idf_python", lambda _path: None)
    monkeypatch.setattr(tc.shutil, "which", lambda _name: None)
    command, env = tc.find_idf()
    assert command == [sys.executable, str(idf / "tools" / "idf.py")]
    assert env["IDF_PATH"] == str(idf)


def test_find_idf_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("IDF_PATH", str(tmp_path / "missing"))
    monkeypatch.setattr(tc.shutil, "which", lambda _name: None)
    monkeypatch.setattr(tc, "_candidate_idf_paths", lambda: [tmp_path / "missing"])
    assert tc.find_idf() is None


def test_missing_for_project_esp_idf(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "find_idf", lambda: None)
    assert tc.missing_for_project("esp-idf", []) == ["idf.py"]
    monkeypatch.setattr(tc, "find_idf", lambda: (["idf.py"], {}))
    assert tc.missing_for_project("esp-idf", []) == []


def test_scan_marks_idf_from_path(tmp_path, monkeypatch):
    idf = _fake_idf(tmp_path)
    monkeypatch.setattr(tc, "find_idf",
                        lambda: ([sys.executable, str(idf / "tools" / "idf.py")],
                                 {"IDF_PATH": str(idf)}))
    monkeypatch.setattr(tc.shutil, "which", lambda name: "" if name == "idf.py" else None)
    rows = {row.name: row for row in tc.scan()}
    assert rows["idf.py"].found
    assert rows["idf.py"].path.endswith("idf.py")


def _tool(name: str, found: bool = True) -> tc.ToolStatus:
    return tc.ToolStatus(name, "", "", "", "C:/x.exe" if found else "")


def test_cmake_does_not_require_make():
    assert tc.missing_for_project("cmake", [_tool("cmake")]) == []


def test_gradle_wrapper_drops_global_gradle(tmp_path):
    from buildforge.detect import Project

    (tmp_path / "gradlew.bat").write_text("@echo off\n", encoding="utf-8")
    wrapper = Project(tmp_path, "gradle", "Java / Gradle",
                      meta={"wrapper": str(tmp_path / "gradlew.bat")})
    assert tc.missing_for_project(wrapper, [_tool("java")]) == []
    no_wrapper = Project(tmp_path, "gradle", "Java / Gradle", meta={})
    assert tc.missing_for_project(no_wrapper, [_tool("java")]) == ["gradle"]
