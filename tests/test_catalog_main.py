from numcraft.catalogs.zcc_main import parse
from numcraft.knowledge import tooling

PAGE = """
===== PAGE 1129 =====
End mill General machining of Al and Al alloys
AL-3E
 Dimensions [mm] Grade
Article D d (h6) H L Teeth Geometry YK30F
AL-3E-D1.0 143 5 0 3A Ɣ
AL-3E-D1.5 1.5 4 4 50 3 A Ɣ
AL-3E-D10.0 10 10 30 75 3 B ż
ƔEx stockżOn demand
===== PAGE 1294 =====
SU drill 3xD General machining
1534SU03/1534SU03C
Article d1 (m7) d 2 (h6) l 1 l2 l3 l4 KDG303
1534SU03-0205 2.05 6 62 20 14 36 ż
1534SU03-0210 2 . 1 6 6 22 01 43 6 Ɣ
ƔEx stockżOn demand
"""


def test_glued_rows_are_repaired():
    rows = {r["article"]: r for r in parse(PAGE)}
    d1 = rows["AL-3E-D1.0"]
    assert (d1["d"], d1["shank_d"], d1["lc"], d1["oal"], d1["z"]) == (1.0, 4.0, 3.0, 50.0, 3)
    dr = rows["1534SU03-0210"]
    assert (dr["d"], dr["shank_d"], dr["oal"], dr["lc"], dr["reach"]) == (2.1, 6.0, 62.0, 20.0, 14.0)
    assert dr["in_stock"] and not rows["AL-3E-D10.0"]["in_stock"]


def test_library_uses_zcc_articles():
    assert len(tooling.catalog_tools()) > 900
    t = tooling.pick_end_mill("aluminum", 16, min_lc=21)
    assert t.article == "AL-3E-D16.0"
    s = tooling.pick_end_mill("steel", 12, min_lc=31)
    assert s.article.startswith("UM-4EL") or s.article.startswith("GM-4EL")


def test_drill_by_diameter_and_depth():
    short = tooling.drill(6.8, 15)
    assert short.article and short.article.startswith("1534SU03") and short.reach >= 15
    deep = tooling.drill(6.8, 30)
    assert deep.article.startswith("1536SU05") and deep.reach >= 30
    assert tooling.drill(6.83, 10).article is None  # нестандартный Ø — обобщённое сверло


def test_reamer_spot_chamfer_from_catalog():
    assert tooling.reamer(10, "H7").article == "3112H7-1000"
    assert tooling.spot_drill().article.startswith("1143SC90")
    assert tooling.chamfer_mill().article.startswith("5601R90")
