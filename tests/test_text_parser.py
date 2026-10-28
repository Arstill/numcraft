from numcraft.models import ChamferFeature, HoleFeature, PocketFeature, SlotFeature, ThreadFeature
from numcraft.parsers.text import parse_description

DESC = """Плита 120х80х20, алюминий 6061. Карман 60х40 глубина 8 R5 в центре.
4 отв. Ø6.6 сквозные по углам с отступом 10. 2 резьбы М6 гл. 12 в точках (30, 40), (90; 40).
Отверстие Ø10H7 сквозное в центре. Паз 30x8 глубиной 5. Фаска 0.5 по контуру. Партия 20 шт."""


def test_full_description():
    r = parse_description(DESC)
    assert r.missing == [] and r.unparsed == []
    p = r.part
    assert p.material == "Алюминий 6061-T6"
    assert (p.size.x, p.size.y, p.size.z) == (120, 80, 20)
    assert p.quantity == 20
    kinds = [type(f) for f in p.features]
    assert kinds == [PocketFeature, HoleFeature, ThreadFeature, HoleFeature, SlotFeature, ChamferFeature]
    pocket, holes, thr, h7 = p.features[:4]
    assert (pocket.length, pocket.width, pocket.depth, pocket.corner_radius) == (60, 40, 8, 5)
    assert pocket.center == (60, 40)
    assert holes.count == 4 and holes.positions[1] == (110, 10) and holes.through
    assert thr.size == "M6" and thr.depth == 12 and thr.positions == [(30, 40), (90, 40)]
    assert h7.fit == "H7" and h7.positions == [(60, 40)]


def test_stock_counterbore_bottom_and_tolerance():
    r = parse_description("Фланец 100х100х15 из стали 45, заготовка 105х105х22, 4 отверстия Ø9 с цековкой Ø15 гл 9 "
                          "по углам 12, резьба M8x1 глубина 10 снизу X50 Y50, ISO 2768-m")
    p = r.part
    assert p.stock.z == 22
    assert p.general_tolerance == "ISO 2768-M"
    hole, thr = p.features
    assert hole.counterbore.diameter == 15 and hole.counterbore.depth == 9
    assert hole.positions[0] == (12, 12)
    assert thr.side == "bottom" and thr.size == "M8x1" and thr.positions == [(50, 50)]


def test_count_prefix_and_through_window():
    r = parse_description("Корпус 150x60x40 7075-T6: окно сквозное 80x30 R6, 6xM5 гл.10")
    pocket, thr = r.part.features
    assert pocket.through and pocket.corner_radius == 6
    assert thr.count == 6 and thr.size == "M5" and thr.depth == 10


def test_missing_data_reported():
    r = parse_description("Деталь из алюминия с отверстием Ø5")
    assert r.part is None
    assert any("марка алюминия" in m for m in r.missing)
    assert any("габарит" in m for m in r.missing)
