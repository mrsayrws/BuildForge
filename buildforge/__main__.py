from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _out(text: str = "") -> None:
    if sys.stdout is not None:
        print(text, flush=True)


def _safe_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def _detect(path: str, as_json: bool) -> int:
    from .detect import KIND_DESCRIPTIONS, detect_project

    try:
        project = detect_project(path)
    except (OSError, NotADirectoryError) as exc:
        _out(f"error: {exc}")
        return 2
    info = {
        "root": str(project.root),
        "kind": project.kind,
        "label": project.label,
        "description": KIND_DESCRIPTIONS.get(project.kind, ""),
        "entry": str(project.entry) if project.entry else "",
        "sources": len(project.sources),
        "meta": {k: v for k, v in project.meta.items() if k != "other_mains"},
    }
    if as_json:
        _out(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        _out(f"project   {info['root']}")
        _out(f"kind      {info['kind']} ({info['label']})")
        _out(f"build     {info['description']}")
        if info["entry"]:
            _out(f"entry     {info['entry']}")
        if info["sources"]:
            _out(f"sources   {info['sources']}")
    return 0


def _doctor(as_json: bool) -> int:
    from .toolchains import scan

    statuses = scan()
    if as_json:
        _out(json.dumps([vars(s) | {"found": s.found} for s in statuses],
                        indent=2, ensure_ascii=False))
        return 0
    _out(f"{'TOOL':<10}{'STATUS':<9}{'GROUP':<13}VERSION / PATH")
    _out("-" * 78)
    for status in statuses:
        mark = "ok" if status.found else "missing"
        detail = status.version or status.install
        _out(f"{status.name:<10}{mark:<9}{status.group:<13}{detail}")
        if status.found:
            _out(f"{'':<32}{status.path}")
        else:
            _out(f"{'':<32}{status.install}")
    found = sum(1 for s in statuses if s.found)
    _out("-" * 78)
    _out(f"{found} of {len(statuses)} tools found")
    return 0


def _build(path: str, args) -> int:
    from .detect import detect_project
    from .diagnostics import counts, parse_log
    from .runner import BuildRunner, command_line, default_jobs, make_plan

    try:
        project = detect_project(path)
    except (OSError, NotADirectoryError) as exc:
        _out(f"error: {exc}")
        return 2

    plan = make_plan(project, release=not args.debug, jobs=args.jobs or default_jobs(),
                     clean=args.clean, custom=args.custom)
    _out(f"project  {project.root}")
    _out(f"kind     {project.kind} ({project.label})")
    if plan.notes:
        _out(f"notes    {plan.notes}")
    if plan.empty:
        _out(f"error: nothing to build — {plan.notes}")
        if project.kind == "esp-idf":
            _out("install ESP-IDF: winget install --id Espressif.EIM-CLI, "
                 "then run 'eim install' and open a new shell so idf.py is on PATH.")
        elif project.kind == "unknown":
            _out("pass --custom \"<command>\" or select the folder that contains "
                 "the project manifest.")
        return 2
    for index, step in enumerate(plan.steps, 1):
        _out(f"step {index}/{len(plan.steps)}  {step.label}")
        _out(f"  $ {command_line(step)}")

    collected: list[str] = []

    def emit(event: dict) -> None:
        kind = event.get("type")
        if kind == "line":
            text = event.get("text", "")
            _out(text)
            if not text.startswith("$ "):
                collected.append(text)
        elif kind == "step":
            _out(f"\n== [{event.get('index')}/{event.get('total')}] "
                 f"{event.get('label')} ==")
        elif kind == "done":
            _out("")

    runner = BuildRunner(emit, timeout_seconds=args.timeout)
    ok = runner.run(plan)
    problems = parse_log("\n".join(collected))
    total = counts(problems)
    if problems:
        _out(f"problems: {total['errors']} error(s), {total['warnings']} warning(s)")
        for problem in problems[: args.max_problems]:
            where = problem.location or "—"
            _out(f"  {problem.severity:<7} {where:<38} {problem.message}")
            if problem.fix:
                _out(f"          fix: {problem.fix}")
        if len(problems) > args.max_problems:
            _out(f"  … {len(problems) - args.max_problems} more")
    _out("build succeeded" if ok else "build failed")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    from . import APP_NAME, __version__

    _safe_console()
    parser = argparse.ArgumentParser(
        prog="buildforge",
        description=f"{APP_NAME} {__version__} — detect, build and explain any project.")
    parser.add_argument("path", nargs="?", help="open the GUI with this project")
    parser.add_argument("--detect", metavar="PATH", help="print project detection")
    parser.add_argument("--doctor", action="store_true", help="show installed toolchains")
    parser.add_argument("--build", metavar="PATH", help="build a project headlessly")
    parser.add_argument("--debug", action="store_true", help="Debug instead of Release")
    parser.add_argument("--jobs", type=int, default=0, help="parallel jobs")
    parser.add_argument("--clean", action="store_true", help="clean before building")
    parser.add_argument("--custom", default="", help="custom build command")
    parser.add_argument("--timeout", type=int, default=0, help="per-step timeout in seconds")
    parser.add_argument("--max-problems", type=int, default=25,
                        help="problems to print in a headless build")
    parser.add_argument("--json", action="store_true", help="JSON output for detect/doctor")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.doctor:
        return _doctor(args.json)
    if args.detect:
        return _detect(args.detect, args.json)
    if args.build:
        return _build(args.build, args)

    from .gui import run

    if args.path:
        from .store import Store

        store = Store()
        target = Path(args.path).expanduser().resolve()
        if target.is_dir():
            store.add_project(str(target))
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
