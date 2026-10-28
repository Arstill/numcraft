from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

from numcraft.models import HoleFeature, PocketFeature
from numcraft.parsers.step import analyze_step_file, to_part

STEP = str(FIXTURES / "plate_pocket_holes.step")


def test_bbox_and_type():
    a = analyze_step_file(STEP)
    assert a.size == (120.0, 80.0, 20.0)
    assert a.units == "мм"
    assert not a.is_3d
    assert a.directions == ["+Z"]


def test_holes_detected():
    a = analyze_step_file(STEP)
    by_d = {}
    for h in a.holes:
        by_d.setdefault(h.diameter, []).append(h)
    assert len(by_d[6.6]) == 4 and all(h.through for h in by_d[6.6])
    assert len(by_d[5.0]) == 2 and not any(h.through for h in by_d[5.0])
    assert by_d[5.0][0].depth == 15
    assert by_d[10.0][0].through and by_d[10.0][0].depth == 12  # сквозь дно кармана
    assert a.inner_radii == [5.0]


def test_to_part():
    a = analyze_step_file(STEP)
    part, notes = to_part(a, "6061")
    pockets = [f for f in part.features if isinstance(f, PocketFeature)]
    assert len(pockets) == 1
    pk = pockets[0]
    assert (pk.length, pk.width, pk.depth, pk.corner_radius, pk.center) == (60, 40, 8, 5, (60, 40))
    h10 = next(f for f in part.features if isinstance(f, HoleFeature) and f.diameter == 10)
    assert h10.z_start == -8
    assert any("под метчик M6" in n for n in notes)
