import json
import re
from pathlib import Path

from numcraft import model3d
from numcraft.models import Box, HoleFeature, Part, PocketFeature
from numcraft.parsers.step import analyze_step_file
from numcraft.pipeline import Inputs, run
from numcraft.planner import plan_part
from numcraft.techsheet import to_html, to_markdown

STEP = Path(__file__).parent / "fixtures" / "plate_pocket_holes.step"


def test_step_edges_tagged():
    res = run(Inputs(step_path=str(STEP), material="6061"))
    m = res.sheet.model3d
    assert m["source"] == "step" and m["size"] == [120.0, 80.0, 20.0]
    tags = [t for e in m["edges"] for t in e["t"]]
    assert "outer" in tags and "top" in tags and "bot" in tags
    pocket = next(f.id for f in res.sheet.part.features if f.type == "pocket")
    hole10 = next(f.id for f in res.sheet.part.features if f.type == "hole" and f.diameter == 10)
    assert pocket in tags and hole10 in tags
    # рёбра в СК детали: Z0 — верх, деталь ниже
    zs = [p[2] for e in m["edges"] for p in e["p"]]
    assert max(zs) <= 0.01 and min(zs) >= -20.01


def test_step_circle_edges_are_round():
    a = analyze_step_file(str(STEP))
    circles = [e for e in a.edges if len(e) > 10]
    assert circles
    for pl in circles:
        cx = sum(p[0] for p in pl) / len(pl)
        cy = sum(p[1] for p in pl) / len(pl)
        rs = [((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5 for p in pl[:-1]]
        if max(rs) - min(rs) < 0.01:  # полная окружность — радиус постоянный
            assert round(max(rs), 2) in (2.5, 3.3, 5.0)


def test_synthetic_model_without_step():
    sheet = plan_part(Part(material="7075", size=Box(x=100, y=60, z=15), features=[
        PocketFeature(length=40, width=20, depth=5, corner_radius=3, center=(50, 30)),
        HoleFeature(diameter=6, positions=[(10, 10)]),
    ]))
    m = model3d.build(sheet)
    assert m["source"] == "model"
    assert any("F1" in e["t"] for e in m["edges"]) and any("F2" in e["t"] for e in m["edges"])
    assert {o["n"] for o in m["ops"]} == {op.number for s in sheet.setups for op in s.operations}


def test_html_contains_viewer_with_valid_json():
    res = run(Inputs(step_path=str(STEP), material="6061"))
    html = to_html(to_markdown(res.sheet), res.sheet)
    assert 'id="nc3d"' in html and "nc3dShow(" in html
    data = re.search(r'<script type="application/json" id="nc3d-data">(.*?)</script>', html, re.S).group(1)
    assert json.loads(data.replace("<\\/", "</"))["edges"]
