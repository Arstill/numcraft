import asyncio

import pytest

pytest.importorskip("langgraph")

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
from graphs.graph import graph  # noqa: E402


def test_graph_text_to_techsheet():
    out = asyncio.run(graph.ainvoke({"text": "Плита 100х60х15 сталь 45, 2 отв. Ø6.6 сквозные X10 Y10, X90 Y50",
                                     "gcode": True}))
    assert out["techsheet_md"].startswith("# Техкарта")
    assert out["gcode"].startswith("%")
    assert "error" not in out or not out["error"]


def test_graph_reports_missing_data():
    out = asyncio.run(graph.ainvoke({"text": "плита из алюминия"}))
    assert "Не хватает данных" in out["techsheet_md"]
    assert out["questions"]


def test_graph_step_input():
    out = asyncio.run(graph.ainvoke({"step_path": str(FIXTURES / "plate_pocket_holes.step"), "material": "7075"}))
    assert "Анализ STEP" in out["techsheet_md"]
