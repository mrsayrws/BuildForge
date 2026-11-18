from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

DEFAULTS = {
    "projects": [],
    "last": "",
    "jobs": 0,
    "timeout": 0,
    "release": True,
    "clean": False,
    "custom": {},
    "labels": {},
    "window": "",
    "history": [],
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    return Path(base) / "BuildForge" if base else Path.home() / ".buildforge"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config_dir() / "config.json"
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            for key, default in DEFAULTS.items():
                value = raw.get(key, default)
                if isinstance(default, list) and not isinstance(value, list):
                    value = list(default)
                if isinstance(default, dict) and not isinstance(value, dict):
                    value = dict(default)
                self.data[key] = value

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    @property
    def projects(self) -> list[str]:
        return self.data["projects"]

    def add_project(self, path: str) -> None:
        path = str(Path(path).resolve())
        if path not in self.projects:
            self.projects.append(path)
        self.data["last"] = path
        self.save()

    def remove_project(self, path: str) -> None:
        if path in self.projects:
            self.projects.remove(path)
        if self.data.get("last") == path:
            self.data["last"] = self.projects[-1] if self.projects else ""
        self.save()

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def record_build(self, root: str, kind: str, ok: bool, seconds: float) -> None:
        self.data["history"].insert(0, {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "root": root,
            "kind": kind,
            "ok": bool(ok),
            "seconds": round(seconds, 1),
        })
        del self.data["history"][60:]
        self.save()
