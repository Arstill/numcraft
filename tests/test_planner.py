import pytest

from numcraft.models import Box, HoleFeature, Part, PocketFeature, ThreadFeature
from numcraft.planner import (ST_DRILL, ST_REAM, ST_SPOT, ST_TAP, plan_part)


def _part(material="6061", **kw):
    return Part(name="Тест", material=material, size=Box(x=120, y=80, z=20), features=[
        PocketFeature(length=60, width=40, depth=8, corner_radius=5, center=(60, 40)),
        HoleFeature(diameter=6.6, count=4, positions=[(10, 10), (110, 10), (10, 70), (110, 70)]),
        HoleFeature(diameter=10, fit="H7", positions=[(60, 40)]),
        ThreadFeature(size="M6", depth=12, count=2, positions=[(30, 40), (90, 40)]),
    ], **kw)


def test_two_setups_with_auto_stock():
    sheet = plan_part(_part())
    assert [s.side for s in sheet.setups] == ["top", "bottom"]
    assert sheet.stock.z >= 20 + 1 + 5
    assert sheet.setups[1].operations[0].strategy.startswith("Face")


def test_operation_order():
    ops = plan_part(_part()).setups[0].operations
    stages = [o.stage for o in ops]
    assert stages == sorted(stages)
    first = {k: next(i for i, o in enumerate(ops) if o.stage == k) for k in (ST_SPOT, ST_DRILL, ST_TAP, ST_REAM)}
    assert first[ST_SPOT] < first[ST_DRILL] < first[ST_TAP] < first[ST_REAM]
    assert ops[0].strategy.startswith("Face")


def test_tool_numbers_unique_and_reused():
    sheet = plan_part(_part())
    nums = [t.number for t in sheet.tools]
    assert nums == list(range(1, len(nums) + 1))
    face_ops = [o for s in sheet.setups for o in s.operations if o.strategy.startswith("Face")]
    assert len({o.tool.number for o in face_ops}) == 1  # одна торцевая фреза на оба установа


def test_reaming_and_tap_drill():
    ops = [o for s in plan_part(_part()).setups for o in s.operations]
    ream = next(o for o in ops if o.cycle == "G85")
    assert ream.tool.diameter == 10
    pre = next(o for o in ops if o.cycle in ("G81", "G73", "G83") and o.tool.kind == "drill" and 9 < o.tool.diameter < 10)
    assert pre.tool.diameter == pytest.approx(9.8)
    tap = next(o for o in ops if o.cycle == "G84")
    assert tap.tool.article == "4701US-M6-6H"  # глухая М6 — метчик ZCC со спиральной канавкой
    tap_drill = next(o for o in ops if o.tool.kind == "drill" and o.tool.diameter == tap.tool.core_drill)
    assert tap.tool.core_drill == 5.1  # сверло под резьбу по каталогу ZCC
    assert tap_drill.z_depth < tap.z_depth  # сверлим глубже резьбы
    assert tap.cutting.feed == pytest.approx(tap.cutting.rpm * 1.0)


def test_pocket_corner_radius_limits_finisher():
    ops = plan_part(_part()).setups[0].operations
    walls = next(o for o in ops if o.title.startswith("Чистовая стенок"))
    assert walls.tool.diameter <= 2 * 5 - 0.5
    assert any("Дообработка углов" in o.title for o in ops)


def test_bottom_features_are_flipped():
    p = Part(material="сталь 45", size=Box(x=100, y=60, z=15), datum="corner", features=[
        HoleFeature(diameter=6, side="bottom", through=False, depth=5, positions=[(20, 10)])])
    sheet = plan_part(p)
    bottom = next(s for s in sheet.setups if s.side == "bottom")
    drill = next(o for o in bottom.operations if o.tool.kind == "drill")
    assert drill.positions == [(20, 50)]
    assert bottom.wcs == "G55"


def test_steel_uses_steel_tools():
    sheet = plan_part(_part(material="1045"))
    mills = [t for t in sheet.tools if t.kind == "end_mill"]
    assert mills and all(t.for_group == "steel" for t in mills)


def test_counterbore_hole_is_drilled():
    p = Part(material="6061", size=Box(x=60, y=60, z=15), features=[
        HoleFeature(diameter=6.6, positions=[(30, 30)], counterbore={"diameter": 11, "depth": 6.5})])
    ops = [o for s in plan_part(p).setups for o in s.operations]
    assert any(o.tool.kind == "drill" and o.tool.diameter == 6.6 for o in ops)
    assert any(o.title.startswith("Цековка") for o in ops)


def test_risk_for_deep_small_radius_pocket():
    p = Part(material="7075", size=Box(x=120, y=80, z=40), features=[
        PocketFeature(length=60, width=40, depth=30, corner_radius=2)])
    sheet = plan_part(p)
    assert any(r.topic == "Вылет" and r.level == "высокий" for r in sheet.risks)


def test_stock_smaller_than_part_rejected():
    with pytest.raises(ValueError):
        plan_part(Part(material="6061", size=Box(x=100, y=50, z=10), stock=Box(x=90, y=50, z=12)))


def test_order_face_contour_pockets_holes():
    ops = plan_part(_part()).setups[0].operations
    first = {}
    for i, o in enumerate(ops):
        kind = ("face" if o.geom == "face" else "contour" if o.geom.startswith("outer") else
                "pocket" if o.geom.startswith("pocket") else "hole" if o.cycle else "other")
        first.setdefault(kind, i)
    assert first["face"] < first["contour"] < first["pocket"] < first["hole"]
    # чистовая контура — до карманов (контур готов до переворота)
    fin_contour = max(i for i, o in enumerate(ops) if o.geom.startswith("outer"))
    assert fin_contour < first["pocket"]


def test_datum_center_and_stock_top():
    sheet = plan_part(_part())
    s1, s2 = sheet.setups[:2]
    assert "центр заготовки" in s1.datum[0] and "верх заготовки" in s1.datum[1]
    assert s1.z_shift == 1.0  # торцовка 1 мм: верх детали на Z-1
    assert "низ детали" in s2.datum[1]
    drill = next(o for o in s1.operations if o.cycle and o.tool.kind == "drill" and o.tool.diameter == 6.6)
    assert (-50.0, -30.0) in drill.positions  # отверстие (10; 10) от центра плиты 120×80


def test_bottom_through_holes_merged_into_top_setup():
    p = Part(material="6061", size=Box(x=100, y=60, z=15), stock=Box(x=100, y=60, z=15), features=[
        HoleFeature(diameter=6.6, side="bottom", positions=[(20, 10)])])
    sheet = plan_part(p)
    assert [s.side for s in sheet.setups] == ["top"]
