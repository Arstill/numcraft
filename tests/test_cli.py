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


def test_manual_stock_callback():
    from numcraft.models import Box
    from numcraft.pipeline import Inputs, run

    seen = {}

    def ask(part, proposed):
        seen["proposed"] = proposed
        return Box(x=130, y=90, z=28)

    res = run(Inputs(step_path=str(FIXTURES / "plate_pocket_holes.step"), material="6061"), ask_stock=ask)
    assert seen["proposed"].x >= 120
    assert (res.sheet.stock.x, res.sheet.stock.y, res.sheet.stock.z) == (130, 90, 28)
    assert res.sheet.gcode is None
