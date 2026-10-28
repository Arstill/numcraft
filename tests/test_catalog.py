from numcraft.catalogs.zcc import parse_pages
from numcraft.knowledge import tooling
from numcraft.models import Box, Part, ThreadFeature
from numcraft.planner import plan_part

PAGE = """C 8
4701US
d1 P d2 d3 l1 l2 l3 d HG23 HG43
4701US-M6-6H 2P M6 1 6 4,6 80 10 35 5,1 ● ○
4701UCS-M8-6H 2P M8 1,25 8 6,3 90 13 35 6,8 ○ ○
– 40° right-hand spiral flute: form C
– Shank type: DIN 371
– Blind hole thread
"""


def test_parse_tap_table():
    rows = parse_pages([PAGE])
    assert [r["article"] for r in rows] == ["4701US-M6-6H", "4701UCS-M8-6H"]
    m6, m8 = rows
    assert m6["hole"] == "blind" and m6["shank_din"] == 371 and m6["core_drill"] == 5.1 and m6["in_stock"]
    assert m8["internal_coolant"] and not m8["in_stock"]


def test_library_has_zcc_taps():
    assert len(tooling.catalog_taps()) > 100


def test_tap_choice_by_hole_type_and_depth():
    assert tooling.tap("M8", through=False, depth=20).article == "4701US-M8-6H"
    assert tooling.tap("M8", through=True, depth=20).article == "4702U-M8-6H"
    # глубокая резьба: DIN 371 (l3 = 35) не достаёт — берётся DIN 376 с тонким хвостовиком
    assert tooling.tap("M8", through=False, depth=50).article == "4601US-M8-6H"
    assert tooling.tap("M10x1", through=False, depth=10).article == "4701US-M10*1-6H"


def test_tap_reach_risk():
    sheet = plan_part(Part(material="сталь 45", size=Box(x=60, y=60, z=80), features=[
        ThreadFeature(size="M6", depth=60, positions=[(30, 30)])]))
    assert any(r.topic == "Длина метчика" for r in sheet.risks)
