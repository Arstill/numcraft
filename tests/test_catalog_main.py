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


TWO_GRADES = """
===== PAGE 1398 =====
SC drill – NC tapping device 90° General machining
1143SC90
Article d1 (h6) d 2 (h6) l 1 l2 KDG303 YK20F
1143SC90-0500 5 5 62 10 Ɣż
1143SC90-1000 10 10 89 20 Ɣ
ƔEx stockżOn demand
"""


def test_grade_decides_material():
    rows = parse(TWO_GRADES)
    by = {(r["article"], r["grade"]): r for r in rows}
    assert by[("1143SC90-0500", "KDG303")]["group"] == "steel" and by[("1143SC90-0500", "KDG303")]["in_stock"]
    al = by[("1143SC90-0500", "YK20F")]
    assert al["group"] == "aluminum" and not al["in_stock"]
    assert ("1143SC90-1000", "YK20F") not in by  # одна отметка — только первая марка
    su = {r["group"] for r in parse(PAGE) if r["series"] == "1534SU03"}
    assert su == {"steel"}  # SU — KDG303, для стали


def test_aluminum_never_gets_steel_tools():
    # Ø4.5 есть на складе в SU (KDG303) — но для алюминия нужно SC (YK20F), пусть и под заказ
    al = tooling.drill(4.5, 12, "aluminum")
    assert al.article.startswith(("1105SC03", "1101SC05")) and "YK20F" in al.coating
    st = tooling.drill(4.5, 12, "steel")
    assert st.article.startswith("1534SU03") and "KDG303" in st.coating
    assert tooling.spot_drill(group="aluminum").article == "1143SC90-0500"
    assert "YK20F" in tooling.spot_drill(group="aluminum").coating
    assert "KDG303" in tooling.spot_drill(group="steel").coating
    # фасочники и развёртки ZCC — только для стали; для алюминия обобщённые с явной пометкой
    for t in (tooling.chamfer_mill(group="aluminum"), tooling.reamer(10, "H7", group="aluminum")):
        assert t.article is None and "нет в каталоге ZCC для алюминия" in t.label()
    assert tooling.reamer(10, "H7", group="steel").article == "3112H7-1000"
    for d in (3, 6, 10, 12):
        t = tooling.pick_end_mill("aluminum", d, min_d=d)
        assert t.for_group == "aluminum" and t.article.startswith("AL-")
    ball = tooling.ball_mill(6, "aluminum")
    assert ball.for_group == "aluminum" and ball.article.startswith(("AL-2B", "NM-2B"))
    necked = tooling.pick_end_mill("aluminum", 4, min_lc=22, min_d=3)
    assert necked.for_group == "aluminum"
    for t in (tooling.drill(d, 3 * d, "aluminum") for d in (2.5, 3.3, 4.2, 5, 6.8, 8.5, 10.2)):
        assert t.for_group == "aluminum"
