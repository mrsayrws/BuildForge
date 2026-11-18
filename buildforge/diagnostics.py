from __future__ import annotations

import re
from dataclasses import dataclass

SEVERITY_ORDER = {"error": 0, "warning": 1, "note": 2}

GCC_RE = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^:\n][^:\n]*?):(?P<line>\d+)"
    r"(?::(?P<col>\d+))?:\s*(?P<sev>fatal error|error|warning|note):\s*(?P<msg>.*)$"
)
MSBUILD_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+)(?:,(?P<col>\d+))?\)\s*:\s*"
    r"(?P<sev>error|warning)\s+(?P<code>[A-Za-z]+\d+)\s*:\s*(?P<msg>.+)$"
)
MSBUILD_BARE_RE = re.compile(
    r"^(?P<sev>error|warning)\s+(?P<code>[A-Za-z]+\d+)\s*:\s*(?P<msg>.+)$"
)
CMAKE_AT_RE = re.compile(
    r"^CMake (?P<sev>Error|Warning) at (?P<file>.+?):(?P<line>\d+)"
    r"(?:\s*\((?P<ctx>[^)]*)\))?:\s*$"
)
CMAKE_BARE_RE = re.compile(
    r"^CMake (?P<sev>Error|Warning)(?: \(dev\))?:\s*(?P<msg>.+)$"
)
PY_LOC_RE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)')
PY_ERR_RE = re.compile(
    r"^(?P<code>[A-Za-z_]*Error|[A-Za-z_]*Exception|SyntaxError|IndentationError|"
    r"TabError|ModuleNotFoundError):\s*(?P<msg>.*)$"
)
RUST_RE = re.compile(r"^(?P<sev>error|warning)(?:\[(?P<code>[A-Z]\d+)\])?:\s*(?P<msg>.+)$")
RUST_LOC_RE = re.compile(r"^\s*-->\s*(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)")
NPM_RE = re.compile(r"^npm (?:ERR!|error)\s*(?P<msg>.*)$")
GENERIC_RE = re.compile(r"^\s*(?P<sev>error|fatal error):\s*(?P<msg>.+)$", re.IGNORECASE)

NOISE = re.compile(
    r"^(?:\s*Build FAILED\.|\s*Build succeeded\.|\s*\d+ Error\(s\)|\s*\d+ Warning\(s\)|"
    r"\s*FAILED:|\s*ninja: |\s*\[?\d+/\d+\]?)", re.IGNORECASE
)

RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("cs0246", "type or namespace name"),
     "A type or namespace used in the code is not known to the compiler.",
     "Add the missing using directive, or add the NuGet PackageReference for it, then restore."),
    (("cs1061", "does not contain a definition"),
     "The member you call does not exist on that type (often a version mismatch).",
     "Check the package version and the spelling; align the package with the API you target."),
    (("cs0103", "does not exist in the current context"),
     "The name is not visible here: missing using, typo, or wrong class.",
     "Add the correct using statement or qualify the name with its namespace."),
    (("cs1002", "expected ';'", "expected \";\""),
     "C# syntax error: a statement is not terminated.",
     "Add the missing semicolon on the reported line or the line before it."),
    (("cs0161", "not all code paths return a value"),
     "A non-void method can finish without returning a value.",
     "Add a return on every branch, or throw at the end."),
    (("netsdk1045",),
     "The installed .NET SDK is too old for the project's TargetFramework.",
     "Install a newer SDK (dotnet.microsoft.com) or lower <TargetFramework> in the .csproj."),
    (("netsdk1004",),
     "The project assets file is missing; restore never ran.",
     "Run dotnet restore, then build again."),
    (("'iostream' file not found", "iostream: no such file"),
     "The compiler cannot find the C++ standard library headers.",
     "You are likely using clang without MSVC headers; build with g++ from w64devkit or install MSVC."),
    (("no such file or directory", ".h"),
     "A header included by the code was not found.",
     "Fix the include path (-I) or install the library that provides the header."),
    (("undefined reference to",),
     "The symbol is declared but its implementation or library was not linked.",
     "Add the missing .cpp/source to the build, or link the library (-lname) after the objects."),
    (("cannot find -l",),
     "The linker cannot find a library you asked for.",
     "Install the library and add its -L path; check that its architecture matches the compiler."),
    (("was not declared in this scope", "is not a member of"),
     "The compiler does not know this name at this point in the file.",
     "Include the header that declares it, add the namespace, or fix the spelling."),
    (("expected primary-expression", "expected expression"),
     "A syntax error near this token, often an unbalanced bracket or a missing operand.",
     "Look at the previous line for a missing ), ], ; or a mistyped expression."),
    (("invalid conversion from", "cannot convert"),
     "The assigned types are incompatible.",
     "Use an explicit cast only when it is safe, or change the variable/parameter type."),
    (("ld returned 1 exit status", "linker command failed"),
     "The linker failed; the real reason is one of the errors above it.",
     "Fix the first undefined-reference or cannot-find error in the log."),
    (("lnk1104",),
     "The linker cannot open the output file, usually because the program is still running.",
     "Close the running executable (or the process holding the file) and build again."),
    (("lnk2019",),
     "An external symbol is unresolved: the implementation or library is missing.",
     "Add the source/library that defines the symbol and match calling conventions."),
    (("c1083",),
     "MSVC cannot open an include file.",
     "Add the include directory to the project or install the missing SDK component."),
    (("msb1003", "msb1009"),
     "MSBuild did not find a project or solution in this folder.",
     "Open the folder that contains the .sln/.csproj, or pass the project path."),
    (("e0308", "mismatched types"),
     "Rust found a value of a different type than expected.",
     "Convert explicitly (as, From/Into) or fix the function signature."),
    (("e0432", "unresolved import", "e0433"),
     "The crate or module is not available.",
     "Add the dependency to Cargo.toml and run cargo build again."),
    (("modulenotfounderror", "no module named"),
     "Python cannot import a module that is not installed.",
     "Activate the right environment and pip install the package."),
    (("indentationerror", "taberror"),
     "Python indentation is inconsistent (tabs vs spaces).",
     "Use one indentation style across the file; Python 3 forbids mixed tabs/spaces."),
    (("syntaxerror",),
     "The file is not valid Python syntax.",
     "Check the reported line and the line before it: colon, brackets, quotes."),
    (("cannot find module", "module not found: error"),
     "Node.js cannot resolve an imported module.",
     "Run npm install (or fix the import path / package name)."),
    (("missing script",),
     "npm was asked for a script name that package.json does not define.",
     "Add the script to package.json or select another build command."),
    (("eaddrinuse",),
     "The requested TCP port is already in use.",
     "Stop the process using that port or choose another port."),
    (("permission denied", "access is denied"),
     "A file or folder cannot be written or executed.",
     "Close the program using it, or run from a writable folder (not Program Files)."),
    (("no rule to make target",),
     "Make cannot find a file or rule referenced by the Makefile.",
     "Check the target path and generate the missing file (configure step)."),
    (("out of memory", "std::bad_alloc", "heap limit"),
     "The machine or process ran out of memory during the build.",
     "Lower parallelism (-j) and close memory-heavy apps."),
    (("not recognized as an internal or external command", "command not found"),
     "The tool is not installed or not on PATH.",
     "Install the toolchain and reopen the terminal so PATH is refreshed."),
    (("cmake_cxx_compiler not set", "no cmake_cxx_compiler", "cmake_c_compiler not set"),
     "CMake could not find a working C++ compiler for the chosen generator.",
     "Install g++ (w64devkit) or MSVC Build Tools, then rebuild with 'clean first' "
     "so CMake re-detects the toolchain."),
    (("idf.py", "espressif"),
     "This is an ESP-IDF build, but idf.py could not run — ESP-IDF is not installed "
     "or not on PATH.",
     "Install ESP-IDF (winget install --id Espressif.EIM-CLI, then run: eim install), "
     "open a new terminal so idf.py is on PATH, and build again."),
    (("failed to resolve component",),
     "ESP-IDF cannot find a component named by the project.",
     "Check the component name/folder under components/, or include the managed "
     "component in idf_component.yml and run idf.py reconfigure."),
    (("idf_path", "esp-idf", "idf_component_register", "/tools/cmake/project.cmake"),
     "This is an ESP-IDF firmware project; CMake cannot find the ESP-IDF build system.",
     "Open the ESP-IDF command prompt (export.bat / export.ps1) so IDF_PATH is set, "
     "then rebuild — or set a custom command that calls idf.py build."),
    (("could not find requested file",),
     "An include()/find_package() file referenced by CMake does not exist here.",
     "Check the path relative to the source directory; the project may need a "
     "submodule init, a toolchain file, or a missing dependency bundle."),
    (("nmake",),
     "The default MSVC generator needs nmake, which is not installed.",
     "Install Visual Studio Build Tools or configure with Ninja + g++ instead."),
    (("cmake error", "could not find"),
     "CMake could not configure the project (missing dependency, generator or compiler).",
     "Read the first CMake error line; install the missing package or choose a generator."),
    (("error ts", "tsc"),
     "TypeScript reported a type error; JS output may still exist.",
     "Fix the reported type or relax the compiler option for that file."),
]


def explain(code: str, message: str) -> tuple[str, str]:
    haystack = f"{code} {message}".lower()
    for needles, explanation, fix in RULES:
        if any(n in haystack for n in needles):
            return explanation, fix
    return "", ""


@dataclass
class Problem:
    severity: str
    message: str
    code: str = ""
    file: str = ""
    line: int = 0
    column: int = 0
    explanation: str = ""
    fix: str = ""
    raw: str = ""

    @property
    def location(self) -> str:
        if not self.file:
            return ""
        tail = f"{self.file}:{self.line}" if self.line else self.file
        if self.column:
            tail += f":{self.column}"
        return tail


def _mk(severity: str, message: str, raw: str, code: str = "",
        file: str = "", line: int = 0, column: int = 0) -> Problem:
    explanation, fix = explain(code, message)
    return Problem(severity.lower(), message.strip(), code, file, line, column,
                   explanation, fix, raw.rstrip())


def parse_log(text: str) -> list[Problem]:
    lines = text.splitlines()
    problems: list[Problem] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or NOISE.match(stripped):
            i += 1
            continue

        m = CMAKE_AT_RE.match(stripped)
        if m:
            file = m["file"]
            line = int(m["line"])
            context = (m["ctx"] or "").strip()
            message = ""
            j = i + 1
            while j < len(lines) and j <= i + 6:
                following = lines[j]
                text = following.strip()
                if text and not following[:1].isspace():
                    break
                if text:
                    message = f"{message} {text}".strip() if message else text
                    if len(message) > 200:
                        break
                j += 1
            if context and message:
                message = f"{message} ({context})"
            problems.append(_mk(m["sev"].lower(), message or f"CMake issue in {file}",
                                raw, "CMAKE", file, line))
            i = max(i + 1, j)
            continue

        m = CMAKE_BARE_RE.match(stripped)
        if m:
            problems.append(_mk(m["sev"].lower(), m["msg"], raw, "CMAKE"))
            i += 1
            continue

        m = MSBUILD_RE.match(stripped)
        if m:
            problems.append(_mk(m["sev"], m["msg"], raw, m["code"], m["file"],
                                int(m["line"]), int(m["col"] or 0)))
            i += 1
            continue

        m = MSBUILD_BARE_RE.match(stripped)
        if m:
            problems.append(_mk(m["sev"], m["msg"], raw, m["code"]))
            i += 1
            continue

        m = GCC_RE.match(stripped)
        if m and not stripped.startswith(("http://", "https://")):
            sev = "error" if "error" in m["sev"] else m["sev"]
            problems.append(_mk(sev, m["msg"], raw, "",
                                m["file"], int(m["line"]), int(m["col"] or 0)))
            i += 1
            continue

        m = RUST_RE.match(stripped)
        if m:
            sev = m["sev"]
            code = m["code"] or ""
            file = line = col = 0
            for look in lines[i + 1:i + 4]:
                lm = RUST_LOC_RE.match(look)
                if lm:
                    file = lm["file"].strip()
                    line = int(lm["line"])
                    col = int(lm["col"])
                    break
            problems.append(_mk(sev, m["msg"], raw, code, file, line, col))
            i += 1
            continue

        m = PY_LOC_RE.match(raw)
        if m:
            file = m["file"]
            line = int(m["line"])
            for j in range(i + 1, min(i + 4, len(lines))):
                em = PY_ERR_RE.match(lines[j].strip())
                if em:
                    problems.append(_mk("error", em["msg"], lines[j], em["code"],
                                        file, line))
                    i = j
                    break
            i += 1
            continue

        em = PY_ERR_RE.match(stripped)
        if em:
            problems.append(_mk("error", em["msg"], raw, em["code"]))
            i += 1
            continue

        m = NPM_RE.match(stripped)
        if m and m["msg"].strip():
            msg = m["msg"].strip()
            if not msg.lower().startswith(("code ", "lifecycle ", "failed at ",
                                           "a complete log")):
                problems.append(_mk("error", msg, raw, "NPM"))
            i += 1
            continue

        m = GENERIC_RE.match(stripped)
        if m:
            problems.append(_mk("error", m["msg"], raw))
            i += 1
            continue

        i += 1

    seen = set()
    unique = []
    for p in problems:
        key = (p.file, p.line, p.column, p.message, p.code)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    unique.sort(key=lambda p: (SEVERITY_ORDER.get(p.severity, 3), p.file, p.line))
    return unique


def counts(problems: list[Problem]) -> dict:
    errors = sum(1 for p in problems if p.severity == "error")
    warnings = sum(1 for p in problems if p.severity == "warning")
    return {"errors": errors, "warnings": warnings, "total": len(problems)}
