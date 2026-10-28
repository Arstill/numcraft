import shutil
from pathlib import Path

from numcraft.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_drop_files_without_description(tmp_path, monkeypatch):
    """Перетаскивание файлов: STEP + чертёж, без описания → техкарта и УП рядом с моделью."""
    step = tmp_path / "корпус.step"
    shutil.copy(FIXTURES / "plate_pocket_holes.step", step)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["plan", str(step), "--material", "6061", "--gcode"]) == 0
    html = tmp_path / "корпус_техкарта.html"
    assert html.exists() and (tmp_path / "корпус_техкарта.md").exists() and (tmp_path / "корпус.nc").exists()
    text = html.read_text(encoding="utf-8")
    assert "<h1>Техкарта: корпус</h1>" in text and "<table>" in text


def test_step_without_material_asks(tmp_path, monkeypatch, capsys):
    step = tmp_path / "деталь.stp"
    shutil.copy(FIXTURES / "plate_pocket_holes.step", step)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["plan", str(step)]) == 2
    assert "материал" in capsys.readouterr().err
