from buildforge.diagnostics import counts, parse_log


def test_gcc_error():
    log = """main.cpp: In function 'int main()':
main.cpp:3:5: error: 'x' was not declared in this scope
    3 |     x = 1;
      |     ^
make: *** [Makefile:2: all] Error 1
"""
    problems = parse_log(log)
    assert len(problems) == 1
    p = problems[0]
    assert p.severity == "error"
    assert p.file == "main.cpp"
    assert p.line == 3
    assert p.column == 5
    assert "not declared in this scope" in p.message
    assert p.explanation and p.fix


def test_gcc_warning_and_note_ordering():
    log = """a.cpp:1:1: warning: unused variable 'x'
a.cpp:2:1: note: declared here
a.cpp:3:1: error: expected ';' before '}' token
"""
    problems = parse_log(log)
    assert [p.severity for p in problems] == ["error", "warning", "note"]


def test_msbuild_error_with_code():
    log = ("C:\\src\\Program.cs(12,5): error CS0246: The type or namespace name "
           "'Foo' could not be found (are you missing a using directive?)\n")
    problems = parse_log(log)
    assert len(problems) == 1
    p = problems[0]
    assert p.code == "CS0246"
    assert p.file == "C:\\src\\Program.cs"
    assert (p.line, p.column) == (12, 5)
    assert "namespace" in p.explanation


def test_netsdk_version_rule():
    log = ("error NETSDK1045: The current .NET SDK does not support targeting "
          ".NET 9.0.\n")
    problems = parse_log(log)
    assert problems[0].code == "NETSDK1045"
    assert "SDK is too old" in problems[0].explanation


def test_python_traceback():
    log = """Traceback (most recent call last):
  File "app.py", line 10, in <module>
    import requests
ModuleNotFoundError: No module named 'requests'
"""
    problems = parse_log(log)
    assert len(problems) == 1
    p = problems[0]
    assert p.file == "app.py"
    assert p.line == 10
    assert p.code == "ModuleNotFoundError"
    assert "pip install" in p.fix


def test_rust_error_with_location():
    log = """error[E0432]: unresolved import `serde`
 --> src/main.rs:2:5
  |
2 | use serde::Serialize;
  |     ^^^^^ no `serde` external crate
"""
    problems = parse_log(log)
    assert len(problems) == 1
    p = problems[0]
    assert p.code == "E0432"
    assert p.file == "src/main.rs"
    assert (p.line, p.column) == (2, 5)


def test_npm_error_skips_metadata_lines():
    log = """npm ERR! code ELIFECYCLE
npm ERR! missing script: build
npm ERR! A complete log of this run can be found in:
"""
    problems = parse_log(log)
    assert len(problems) == 1
    assert "missing script" in problems[0].message.lower()


def test_deduplication_and_counts():
    log = """main.cpp:3:5: error: expected ';' before '}' token
main.cpp:3:5: error: expected ';' before '}' token
main.cpp:9:1: warning: unused parameter 'argc'
"""
    problems = parse_log(log)
    assert len(problems) == 2
    assert counts(problems) == {"errors": 1, "warnings": 1, "total": 2}


def test_noise_is_ignored():
    log = """Build FAILED.
    0 Error(s)
    0 Warning(s)
ninja: no work to do.
"""
    assert parse_log(log) == []


def test_unknown_error_still_reported():
    log = "error: something completely custom happened\n"
    problems = parse_log(log)
    assert len(problems) == 1
    assert problems[0].severity == "error"
    assert problems[0].explanation == ""


def test_cmake_error_with_location():
    log = """CMake Error at CMakeLists.txt:5 (include):
  include could not find requested file:

    /tools/cmake/project.cmake

CMake Error: CMAKE_CXX_COMPILER not set, after EnableLanguage
-- Configuring incomplete, errors occurred!
"""
    problems = parse_log(log)
    assert len(problems) == 2
    first = [p for p in problems if p.file == "CMakeLists.txt"][0]
    assert first.line == 5
    assert "could not find requested file" in first.message
    assert "ESP-IDF" in first.explanation
    compiler = [p for p in problems if not p.file][0]
    assert "compiler" in compiler.explanation.lower()


def test_cmake_warning_severity():
    log = "CMake Warning at CMakeLists.txt:3 (message):\n  old cmake soon\n"
    problems = parse_log(log)
    assert problems and problems[0].severity == "warning"
