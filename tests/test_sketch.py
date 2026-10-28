import re

from numcraft.models import Box, HoleFeature, Part, PocketFeature, SlotFeature, ThreadFeature
from numcraft.planner import plan_part
from numcraft.sketch import setup_svg
from numcraft.techsheet import to_html, to_markdown


def _sheet():
    return plan_part(Part(name="Плита", material="6061", size=Box(x=120, y=80, z=20), features=[
        PocketFeature(length=60, width=40, depth=8, corner_radius=5, center=(60, 40)),
        HoleFeature(diameter=6.6, count=2, positions=[(10, 10), (110, 70)]),
        HoleFeature(diameter=10, positions=[(60, 40)]),
        ThreadFeature(size="M6", depth=10, side="bottom", positions=[(20, 20)]),
        SlotFeature(length=30, width=8, depth=5),
    ]))


def _op(sheet, prefix):
    return next((s, o) for s in sheet.setups for o in s.operations if o.title.startswith(prefix))


def test_every_operation_has_geom_and_selection():
    for s in _sheet().setups:
        for op in s.operations:
            assert op.geom, op.title
            assert op.selection, op.title


def test_pocket_walls_highlighted():
    sheet = _sheet()
    s, op = _op(sheet, "Чистовая стенок: карман")
    svg = setup_svg(sheet, s, op)
    assert 'class="hll"' in svg and "стенки кармана" in svg
    assert "Pockets" not in op.selection and "Contour selection" in op.selection


def test_drill_order_numbers_and_unplaced_slot():
    sheet = _sheet()
    s, op = _op(sheet, "Сверление Ø6.6")
    svg = setup_svg(sheet, s, op)
    assert len(re.findall(r'class="num"', svg)) == 2
    assert "Без координат" in svg and "паз" in svg


def test_hole_inside_pocket_enters_from_floor():
    sheet = _sheet()
    _, op = _op(sheet, "Сверление Ø10")
    assert op.z_start == -8


def test_bottom_setup_flipped_and_html_embeds_svg():
    sheet = _sheet()
    bottom = next(s for s in sheet.setups if s.side == "bottom")
    assert "перевёрнута" in setup_svg(sheet, bottom)
    html = to_html(to_markdown(sheet), sheet)
    assert html.count("<svg") == len(sheet.setups) + sum(len(s.operations) for s in sheet.setups)
    assert "<!--sk:" not in html


def test_hole_on_pocket_wall_is_a_risk():
    sheet = plan_part(Part(material="6061", size=Box(x=120, y=80, z=20), features=[
        PocketFeature(length=60, width=40, depth=8, corner_radius=5, center=(60, 40)),
        ThreadFeature(size="M6", depth=10, positions=[(30, 40)]),
    ]))
    assert any("пересекает стенку" in r.message for r in sheet.risks)
