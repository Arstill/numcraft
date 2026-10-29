"""Н-профиль, построенный в SolidWorks «стоя» (толщина по Y): пазы с двух сторон, цековки снизу,
отверстия через две стенки, скругления R2 — как реальная деталь заказчика."""
from pathlib import Path

from numcraft.models import ChamferFeature, HoleFeature, SlotFeature
from numcraft.parsers.step import analyze_step_file, to_part
from numcraft.pipeline import Inputs, run

STEP = str(Path(__file__).parent / "fixtures" / "h_profile_y_up.step")


def test_recognition():
    part, notes = to_part(analyze_step_file(STEP), "6061")
    assert (part.size.x, part.size.y, part.size.z) == (40, 40, 20)
    slots = {f.side: f for f in part.features if isinstance(f, SlotFeature)}
    assert set(slots) == {"top", "bottom"} and all(s.open_ends and s.width == 34 and s.depth == 5
                                                   for s in slots.values())
    cb = next(f for f in part.features if isinstance(f, HoleFeature) and f.counterbore)
    assert cb.side == "bottom" and cb.z_start == -5 and cb.count == 4  # цековка — со стороны нижнего паза
    walls = next(f for f in part.features if isinstance(f, HoleFeature) and f.diameter == 3.4)
    assert walls.walls == 2 and walls.side in ("front", "back")
    assert {f.side for f in part.features if isinstance(f, ChamferFeature) and f.profile == "round"} == \
        {"top", "bottom"}
    assert any("через 2 стенки" in n for n in notes)


def test_plan_order_and_tools():
    sheet = run(Inputs(step_path=STEP, material="6061")).sheet
    assert [s.side for s in sheet.setups][:2] == ["top", "bottom"] and len(sheet.setups) == 3
    top = sheet.setups[0].operations
    assert top[0].geom == "face" and top[1].geom.startswith("outer")
    rnd = [o for s in sheet.setups for o in s.operations if o.geom == "round_edges"]
    # фрезы-скругления ZCC 5601R…FM — только KMG303 (сталь): для алюминия каталожной нет, это сказано явно
    assert rnd and all(o.tool.kind == "round_mill" and o.tool.article is None
                       and "нет в каталоге ZCC для алюминия" in o.tool.label() for o in rnd)
    assert not any(o.title.startswith("Фаска") for s in sheet.setups for o in s.operations)
    assert not any(r.topic == "СОЖ через инструмент" for r in sheet.risks)


def test_steel_round_mill_from_catalog():
    sheet = run(Inputs(step_path=STEP, material="сталь 45")).sheet
    rnd = [o for s in sheet.setups for o in s.operations if o.geom == "round_edges"]
    assert rnd and all(o.tool.article.startswith("5601R904FM-R20") for o in rnd)
