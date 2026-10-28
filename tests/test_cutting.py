import math

import pytest

from numcraft import cutting
from numcraft.knowledge import tooling
from numcraft.knowledge.machine import load_machine
from numcraft.knowledge.materials import UnknownMaterial, resolve_material


@pytest.fixture
def vf2():
    return load_machine()


def test_material_aliases():
    assert resolve_material("6061-T6").key == "al6061"
    assert resolve_material("В95Т1").key == "al7075"
    assert resolve_material("Сталь 45 ГОСТ 1050").key == "steel45"
    assert resolve_material("AISI 1045").key == "aisi1045"
    with pytest.raises(UnknownMaterial):
        resolve_material("титан ВТ6")


def test_aluminum_small_tool_is_rpm_limited(vf2):
    mat = resolve_material("6061")
    t = tooling.pick_end_mill("aluminum", 6, min_d=6)
    cd = cutting.milling(t, mat, vf2, "adaptive")
    assert cd.rpm == vf2.spindle.max_rpm
    assert any("обороты" in lim for lim in cd.limits)
    assert cd.vc < mat.milling["vc"]["adaptive"]
    # подача считается от реальных оборотов
    assert cd.feed == pytest.approx(cd.fz * t.flutes * cd.rpm, rel=0.01)


def test_12k_spindle_option_raises_rpm():
    mat = resolve_material("6061")
    t = tooling.pick_end_mill("aluminum", 10, min_d=10)
    assert cutting.milling(t, mat, load_machine(max_rpm=12000), "adaptive").rpm == 12000


def test_chip_thinning():
    assert cutting.chip_thinning_factor(10, 5, 2) == 1.0
    f = cutting.chip_thinning_factor(10, 1, 2)
    assert f == pytest.approx(10 / (2 * math.sqrt(1 * 9)), rel=1e-6)
    assert cutting.chip_thinning_factor(10, 0.1, 1.5) == 1.5


def test_steel_slower_than_aluminum(vf2):
    t_al = tooling.pick_end_mill("aluminum", 16, min_d=16)
    t_st = tooling.pick_end_mill("steel", 16, min_d=16)
    al = cutting.milling(t_al, resolve_material("6061"), vf2, "adaptive")
    st = cutting.milling(t_st, resolve_material("сталь 45"), vf2, "adaptive")
    assert st.rpm < al.rpm
    assert st.ae < al.ae


def test_power_within_vf2_for_typical_steel_pocket(vf2):
    t = tooling.pick_end_mill("steel", 16, min_d=16)
    cd = cutting.milling(t, resolve_material("1045"), vf2, "pocket", ap=32, ae=12)
    assert cd.ap == 32 and cd.power_kw <= vf2.available_power_kw(cd.rpm)


def test_power_limit_reduces_ap(vf2):
    weak = vf2.model_copy(deep=True)
    weak.spindle.peak_power_kw = 5.0
    t = tooling.pick_end_mill("steel", 16, min_d=16)
    cd = cutting.milling(t, resolve_material("1045"), weak, "pocket", ap=32, ae=12)
    assert cd.power_kw <= weak.available_power_kw(cd.rpm) + 1e-6
    assert cd.ap < 32
    assert any("мощность" in lim for lim in cd.limits)


def test_tapping_feed_is_rpm_times_pitch(vf2):
    t = tooling.tap("M8", through=False)
    cd = cutting.tapping(t, resolve_material("сталь 45"), vf2)
    assert cd.feed == pytest.approx(cd.rpm * 1.25)


def test_thread_table():
    assert tooling.parse_thread("М10") == (10, 1.5)
    assert tooling.parse_thread("M10x1") == (10, 1.0)
    assert tooling.tap_drill(6, 1.0) == 5.0
    assert tooling.tap_drill(10, 1.0) == 9.0
