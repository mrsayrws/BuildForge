from __future__ import annotations

import os


def _registry_paths() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    parts: list[str] = []
    keys = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ]
    for hive, subkey in keys:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, kind = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if kind == winreg.REG_EXPAND_SZ:
            value = winreg.ExpandEnvironmentStrings(value)
        parts.extend(p for p in value.split(";") if p.strip())
    return parts


def merged_path() -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in [*os.environ.get("PATH", "").split(os.pathsep), *_registry_paths()]:
        entry = raw.strip().strip('"')
        if not entry:
            continue
        key = entry.rstrip("\\").lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(entry)
    return os.pathsep.join(ordered)


def apply() -> None:
    current = os.environ.get("PATH", "")
    merged = merged_path()
    if merged and merged != current:
        os.environ["PATH"] = merged
