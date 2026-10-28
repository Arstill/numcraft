from numcraft.models import Box, HoleFeature, Part, ThreadFeature
from numcraft.parsers.drawing import apply_to_part, parse_notation


def test_notation():
    info = parse_notation("Сталь 45 ГОСТ 1050-2013. Неуказанные предельные отклонения ISO 2768-m. "
                          "2 отв. M6-6H  Ø10H7  4 отв. Ø6.6  Ra 3.2 √Ra1.6")
    assert info.material.lower().startswith("сталь")
    assert info.general_tolerance == "ISO 2768-M"
    assert (10.0, "H7", 1) in info.fits
    assert ("M6", 2) in info.threads
    assert info.ra_values == [1.6, 3.2]


def test_unsupported_material_warning():
    info = parse_notation("Материал Д16Т")
    assert info.material is None and info.unsupported_material
    assert info.warnings


def test_apply_converts_tap_holes_and_sets_fit():
    part = Part(material="6061", size=Box(x=100, y=60, z=20), features=[
        HoleFeature(diameter=5.0, depth=15, through=False, count=2, positions=[(10, 10), (20, 10)]),
        HoleFeature(diameter=10, positions=[(50, 30)]),
    ])
    apply_to_part(part, parse_notation("2 отв. M6  Ø10H7"))
    thr = next(f for f in part.features if isinstance(f, ThreadFeature))
    assert thr.size == "M6" and thr.count == 2 and thr.depth == 12
    assert next(f for f in part.features if isinstance(f, HoleFeature)).fit == "H7"
