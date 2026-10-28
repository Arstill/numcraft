import re

from numcraft.gcode import ascii_comment, generate, num
from numcraft.models import Box, HoleFeature, Part, ThreadFeature
from numcraft.planner import plan_part


def _sheet():
    return plan_part(Part(name="Кронштейн", material="6061", size=Box(x=100, y=60, z=15), features=[
        HoleFeature(diameter=6.6, count=2, positions=[(10, 10), (90, 50)]),
        ThreadFeature(size="M6", depth=10, positions=[(50, 30)]),
        HoleFeature(diameter=8, positions=[], note="без координат"),
    ]))


def test_number_format():
    assert num(10) == "10."
    assert num(-3.5) == "-3.5"
    assert num(-0.0001) == "0."


def test_ascii_comments():
    assert ascii_comment("Кронштейн Ø10") == "KRONSHTEYN D10"


def test_fanuc_program_structure():
    g = generate(_sheet(), "fanuc")
    lines = g.splitlines()
    assert lines[0] == "%" and lines[-1] == "%"
    assert g.count("M30") == 2  # программа на каждый установ
    assert all(line.isascii() for line in lines)
    assert "G43 H01" in g
    assert "M29 S" in g  # жёсткое нарезание FANUC
    assert re.search(r"G98 G84 X50\. Y30\. Z-10\. R5\. F\d+", g)
    assert "NO HOLE COORDINATES" in g
    assert "G91 G28 Z0." in g


def test_haas_dialect():
    g = generate(_sheet(), "haas")
    assert "M29" not in g
    assert "G53 G49 Z0." in g


def test_each_tool_change_has_length_comp():
    g = generate(_sheet(), "fanuc").splitlines()
    for i, line in enumerate(g):
        m = re.match(r"T(\d+) M06", line)
        if m:
            follow = "\n".join(g[i:i + 5])
            assert f"G43 H{int(m.group(1)):02d}" in follow
