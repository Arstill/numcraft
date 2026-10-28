from pathlib import Path

from numcraft.faces import from_face, to_face, to_setup
from numcraft.models import Box
from numcraft.parsers.step import analyze_step_file, to_part
from numcraft.pipeline import Inputs, run
from numcraft.sketch import setup_svg

STEP = str(Path(__file__).parent / "fixtures" / "housing_sides.step")
SIZE = Box(x=100, y=60, z=40)


def test_face_frames_roundtrip():
    for side in ("top", "bottom", "front", "back", "left", "right"):
        p = (12.0, 34.0, -7.0)
        assert all(abs(a - b) < 1e-9 for a, b in zip(from_face(side, *to_face(side, *p, SIZE), SIZE), p))
    # установ на переднюю грань: X станка вдоль X детали, Y — по высоте, Z0 — грань
    assert to_setup("front", 50, 0, -20, SIZE) == (50, 20, 0)


def test_step_features_on_all_sides():
    part, _ = to_part(analyze_step_file(STEP), "6061")
    by = {(f.type, f.side): f for f in part.features}
    assert by[("hole", "left")].positions == [(15.0, 20.0)] and by[("hole", "left")].depth == 10
    assert sorted(by[("hole", "right")].positions) == [(30.0, 12.0), (30.0, 28.0)]
    assert by[("hole", "front")].through
    win = by[("pocket", "front")]
    assert (win.length, win.width, win.depth, win.center) == (30, 12, 15, (25, 12))
    assert by[("pocket", "bottom")].depth == 5
    top = by[("pocket", "top")]
    assert top.depth == 10  # окно спереди не принято за карман сверху


def test_plan_has_setup_per_side_and_sketches():
    res = run(Inputs(step_path=STEP, material="6061"))
    sides = [s.side for s in res.sheet.setups]
    assert sides == ["top", "bottom", "front", "left", "right"]
    assert [s.wcs for s in res.sheet.setups] == ["G54", "G55", "G56", "G57", "G58"]
    front = res.sheet.setups[2]
    drill = next(o for o in front.operations if o.tool.kind == "drill")
    assert drill.positions == [(50.0, 20.0)]
    svg = setup_svg(res.sheet, front, drill)
    assert "Вид на грань" in svg and 'class="hl"' in svg
    tags = {t for e in res.sheet.model3d["edges"] for t in e["t"]}
    assert {f.id for f in res.sheet.part.features} <= tags
