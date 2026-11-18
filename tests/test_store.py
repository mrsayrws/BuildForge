import json
from pathlib import Path

from buildforge.store import DEFAULTS, Store, config_dir


def test_roundtrip(tmp_path):
    config = tmp_path / "config.json"
    store = Store(config)
    store.add_project(str(tmp_path))
    store.set("jobs", 6)
    store.record_build(str(tmp_path), "cpp", True, 1.234)

    again = Store(config)
    assert again.data["jobs"] == 6
    assert again.data["last"] == str(tmp_path.resolve())
    assert again.data["history"][0]["ok"] is True
    assert again.data["history"][0]["seconds"] == 1.2


def test_history_is_capped(tmp_path):
    store = Store(tmp_path / "config.json")
    for i in range(70):
        store.record_build(str(tmp_path), "cpp", i % 2 == 0, 0.1)
    assert len(store.data["history"]) == 60
    assert store.data["history"][0]["ok"] is False
    assert store.data["history"][1]["ok"] is True


def test_remove_project_updates_last(tmp_path):
    store = Store(tmp_path / "config.json")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    store.add_project(str(a))
    store.add_project(str(b))
    store.remove_project(str(b))
    assert store.projects == [str(a.resolve())]
    assert store.data["last"] == str(a.resolve())


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{not json", encoding="utf-8")
    store = Store(config)
    assert store.data["projects"] == []
    assert store.data["release"] is True


def test_wrong_types_are_ignored(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"projects": "oops", "custom": [1, 2],
                                  "jobs": 12}), encoding="utf-8")
    store = Store(config)
    assert store.data["projects"] == []
    assert store.data["custom"] == {}
    assert store.data["jobs"] == 12


def test_new_defaults_survive_reload(tmp_path):
    config = tmp_path / "config.json"
    Store(config).set("labels", {"x": "Nice name"})
    assert Store(config).data["labels"] == {"x": "Nice name"}
    assert set(DEFAULTS) >= {"labels", "timeout"}


def test_config_dir_is_per_user():
    assert str(config_dir()).endswith(("BuildForge", ".buildforge"))
