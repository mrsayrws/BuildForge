import json
import sys

import pytest

import buildforge.__main__ as cli
from buildforge.store import Store


def write(root, name, text=""):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_detect_cli_json(tmp_path, capsys):
    write(tmp_path, "main.cpp", "int main(){return 0;}\n")
    code = cli.main(["--detect", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["kind"] == "cpp"
    assert out["sources"] == 1


def test_detect_cli_missing(tmp_path, capsys):
    assert cli.main(["--detect", str(tmp_path / "missing")]) == 2
    assert "error:" in capsys.readouterr().out


def test_build_cli_runs_custom_command(tmp_path, capsys):
    marker = tmp_path / "built.txt"
    command = (f'{sys.executable} -c "open(r\'{marker}\',\'w\').write(\'ok\')"')
    code = cli.main(["--build", str(tmp_path), "--custom", command])
    capsys.readouterr()
    assert code == 0
    assert marker.read_text() == "ok"


def test_build_cli_reports_failure(tmp_path, capsys):
    command = f'{sys.executable} -c "raise SystemExit(4)"'
    code = cli.main(["--build", str(tmp_path), "--custom", command,
                     "--max-problems", "3"])
    assert code == 1
    assert "build failed" in capsys.readouterr().out


def test_doctor_cli_json(capsys):
    code = cli.main(["--doctor", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert code == 0
    assert any(row["name"] == "python" for row in rows)


def test_store_used_by_gui_path_argument(tmp_path):
    store = Store(tmp_path / "config.json")
    store.add_project(str(tmp_path))
    assert Store(tmp_path / "config.json").projects == [str(tmp_path.resolve())]


def test_gui_smoke(tmp_path):
    tk = pytest.importorskip("tkinter")
    from buildforge.gui import App

    try:
        app = App(Store(tmp_path / "config.json"))
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    try:
        app.update_idletasks()
        assert app.project is None
        app.path_var.set(str(tmp_path))
        write(tmp_path, "main.cpp", "int main(){return 0;}\n")
        app._open_typed_path()
        app.update_idletasks()
        assert app.project is not None and app.project.kind == "cpp"
        assert app.build_btn.instate(["!disabled"])
        app._refresh_plan()
        assert app.plan and not app.plan.empty
    finally:
        app.destroy()


def test_gui_explains_missing_esp_idf(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    import buildforge.gui as gui
    import buildforge.runner as runner
    from buildforge.detect import detect_project

    monkeypatch.setattr(runner, "find_idf", lambda: None)
    shown = {}
    monkeypatch.setattr(gui.messagebox, "showinfo",
                        lambda *args, **kwargs: shown.setdefault("text", args[1]))
    write(tmp_path, "CMakeLists.txt",
          'include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n')
    write(tmp_path, "sdkconfig.defaults", "")
    try:
        app = gui.App(Store(tmp_path / "config.json"))
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    try:
        app._set_project(detect_project(tmp_path))
        app.update_idletasks()
        assert app.project.kind == "esp-idf"
        assert app.build_btn.instate(["!disabled"])
        app._start_build()
        assert "ESP-IDF" in shown["text"]
        assert "eim install" in shown["text"]
        assert "ESP-IDF" in app.status_var.get()
    finally:
        app.destroy()
