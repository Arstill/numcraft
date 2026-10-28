"""Библиотека инструмента и справочник резьб."""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from numcraft.models import Tool, _n

_DIR = Path(__file__).parent

# Метрическая резьба с крупным шагом: размер → (шаг, сверло под резьбу)
METRIC_COARSE = {
    2: (0.4, 1.6), 2.5: (0.45, 2.05), 3: (0.5, 2.5), 4: (0.7, 3.3), 5: (0.8, 4.2),
    6: (1.0, 5.0), 8: (1.25, 6.8), 10: (1.5, 8.5), 12: (1.75, 10.2), 14: (2.0, 12.0),
    16: (2.0, 14.0), 18: (2.5, 15.5), 20: (2.5, 17.5), 24: (3.0, 21.0),
}

# Свёрла, которые обычно есть в наличии (шаг 0.1 до 13 мм) — для подбора под развёртку
MAX_DRILL_D = 20.0
MAX_TWIST_DRILL_PREFERRED = 13.0


def parse_thread(size: str) -> Tuple[float, float]:
    """'M10' → (10, 1.5); 'M10x1' → (10, 1.0). Принимает латиницу и кириллицу."""
    s = size.strip().upper().replace("М", "M").replace("Х", "X").replace("×", "X").replace(",", ".")
    m = re.match(r"M\s*(\d+(?:\.\d+)?)(?:\s*X\s*(\d+(?:\.\d+)?))?", s)
    if not m:
        raise ValueError(f"Не распознана резьба «{size}»")
    d = float(m.group(1))
    if m.group(2):
        return d, float(m.group(2))
    if d not in METRIC_COARSE:
        raise ValueError(f"Нет данных по крупному шагу для M{_n(d)} — укажите шаг явно, напр. M{_n(d)}x1.5")
    return d, METRIC_COARSE[d][0]


def tap_drill(d: float, pitch: float) -> float:
    for size, (p, drill) in METRIC_COARSE.items():
        if math.isclose(size, d) and math.isclose(p, pitch):
            return drill
    return round(d - pitch, 1)


@lru_cache(maxsize=1)
def _library() -> dict:
    with open(_DIR / "tool_library.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _mk(kind: str, row: dict, **kw) -> Tool:
    return Tool(
        kind=kind,
        diameter=float(row["d"]),
        flutes=int(row.get("z", 2)),
        flute_length=float(row.get("lc", 0)),
        overall_length=float(row.get("oal", 0)),
        corner_radius=float(row.get("r", 0)),
        for_group=row.get("group", "any"),
        point_angle=row.get("angle"),
        description=row.get("desc", ""),
        **kw,
    )


def _group_ok(tool_group: str, group: str) -> bool:
    return tool_group in ("any", group)


@lru_cache(maxsize=1)
def catalog_tools() -> list:
    """Инструмент ZCC из основного каталога (knowledge/catalogs/zcc_tools.yaml), если импортирован."""
    path = _DIR / "catalogs" / "zcc_tools.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("tools", [])


KIND_RU = {"end_mill": "Фреза концевая", "ball_mill": "Фреза сферическая", "drill": "Сверло",
           "spot_drill": "Центровка NC 90°", "chamfer_mill": "Фасочная фреза 90°", "reamer": "Развёртка"}


def _cat_tool(r: dict) -> Tool:
    kind = r["kind"]
    extra = ""
    if kind == "end_mill":
        extra = f" z{r.get('z', 0)} Lc{_n(r['lc'])}" + (f", шейка {_n(r['reach'])}" if r.get("reach") else "")
    elif kind == "drill":
        extra = f" {r['xd']}xD" + (" (СОЖ через инструмент)" if r.get("internal_coolant") else "")
    elif kind == "reamer":
        extra = r.get("fit", "")
    elif kind == "ball_mill":
        extra = f" R{_n(r['d'] / 2)}"
    t = Tool(
        kind=kind, diameter=float(r["d"]), flutes=int(r.get("z") or 2), flute_length=float(r.get("lc") or 0),
        overall_length=float(r["oal"]), corner_radius=float(r.get("r") or (r["d"] / 2 if kind == "ball_mill" else 0)),
        for_group=r["group"], point_angle=r.get("angle") or (140 if kind == "drill" else None),
        tool_material="твердый сплав", coating=r.get("grade", ""), article=r["article"], in_stock=r["in_stock"],
        reach=float(r.get("reach") or 0), shank_d=float(r.get("shank_d") or 0),
        description=f"{KIND_RU.get(kind, kind)} ZCC {r['article']} Ø{_n(r['d'])}{extra}",
    )
    return t


def _cat(kind: str, group: str) -> List[dict]:
    return [r for r in catalog_tools() if r["kind"] == kind and _group_ok(r["group"], group)]


def end_mills(group: str, neck: bool = False) -> List[Tool]:
    """Концевые фрезы для группы материала: каталог ZCC (основные серии; запасные — только для недостающих Ø),
    иначе — обобщённая библиотека tool_library.yaml."""
    rows = [r for r in _cat("end_mill", group) if (r.get("length") == "neck") == neck]
    if rows:
        main = [r for r in rows if not r.get("spare")]
        have = {r["d"] for r in main}
        rows = main + [r for r in rows if r.get("spare") and r["d"] not in have]
        return [_cat_tool(r) for r in rows]
    if neck:
        return []
    out = []
    for row in _library()["end_mills"]:
        if _group_ok(row.get("group", "any"), group):
            t = _mk("end_mill", row, coating="без покрытия / ZrN" if group == "aluminum" else "AlTiN")
            if not t.description:
                t.description = f"Фреза концевая Ø{_n(t.diameter)} z{t.flutes} Lc{_n(t.flute_length)}"
            else:
                t.description = f"Фреза концевая Ø{_n(t.diameter)} z{t.flutes} Lc{_n(t.flute_length)} ({t.description})"
            out.append(t)
    return out


def _rank(t: Tool) -> tuple:
    # со склада → толще хвостовик → короче
    return (t.in_stock is False, -(t.shank_d or t.diameter), t.flute_length, t.overall_length)


def pick_end_mill(group: str, max_d: float, min_lc: float = 0.0, min_d: float = 0.0) -> Optional[Tool]:
    """Наибольшая фреза D ≤ max_d, которая достаёт на глубину: Lc ≥ min_lc и общая длина позволяет вылет
    (глубина + 5 мм над деталью при зажиме ≥ 3·хвостовика). Среди равных D — со склада, жёстче, короче.
    Если обычные не достают — фреза с шейкой; иначе — самая длинная (риск отметит risks.py)."""
    cands = [t for t in end_mills(group) if min_d - 1e-6 <= t.diameter <= max_d + 1e-6]
    if not cands:
        return None

    def reaches(t: Tool, by_neck: bool = False, slack: float = 0.0) -> bool:
        need = min_lc - slack
        ok_len = (t.reach if by_neck else t.flute_length) >= need
        grip = max(20.0, 3 * (t.shank_d or t.diameter))
        return ok_len and (not t.overall_length or t.overall_length - grip >= need + 4)

    # точно в размер глубины (без запаса 1 мм) — лучше обычная фреза со склада, чем фреза с шейкой под заказ
    fit = [t for t in cands if reaches(t)] or [t for t in cands if reaches(t, slack=1.0) and t.in_stock is not False]
    if fit:
        best_d = max(t.diameter for t in fit)
        return min((t for t in fit if t.diameter == best_d), key=_rank)
    necked = [t for t in end_mills(group, neck=True) if min_d - 1e-6 <= t.diameter <= max_d + 1e-6
              and reaches(t, by_neck=True)]
    if necked:
        best_d = max(t.diameter for t in necked)
        return min((t for t in necked if t.diameter == best_d), key=_rank)
    best_d = max(t.diameter for t in cands)
    return max((t for t in cands if t.diameter == best_d), key=lambda t: (t.flute_length, t.overall_length))


def face_mill() -> Tool:
    return _mk("face_mill", _library()["face_mills"][0], coating="пластины для Al / стали")


def ball_mill(max_d: float, group: str = "any") -> Optional[Tool]:
    rows = [r for r in _cat("ball_mill", group) if r["d"] <= max_d + 1e-6]
    if rows:
        best = max(r["d"] for r in rows)
        return min((_cat_tool(r) for r in rows if r["d"] == best), key=_rank)
    rows = [r for r in _library()["ball_mills"] if r["d"] <= max_d]
    if not rows:
        return None
    row = max(rows, key=lambda r: r["d"])
    t = _mk("ball_mill", row)
    t.corner_radius = t.diameter / 2
    t.description = f"Фреза сферическая Ø{_n(t.diameter)} (R{_n(t.diameter / 2)})"
    return t


def spot_drill(d: float = 10.0) -> Tool:
    rows = _cat("spot_drill", "any")
    if rows:
        exact = [r for r in rows if math.isclose(r["d"], d)] or rows
        return min((_cat_tool(r) for r in exact), key=lambda t: (t.in_stock is False, abs(t.diameter - d)))
    return _mk("spot_drill", _library()["spot_drills"][0])


def chamfer_mill(d: float = 10.0) -> Tool:
    rows = _cat("chamfer_mill", "any")
    if rows:
        exact = [r for r in rows if math.isclose(r["d"], d)] or rows
        return min((_cat_tool(r) for r in exact), key=lambda t: (t.in_stock is False, abs(t.diameter - d), -t.flutes))
    return _mk("chamfer_mill", _library()["chamfer_mills"][0])


def thread_mill(nominal_d: float) -> Optional[Tool]:
    rows = [r for r in _library()["thread_mills"] if r["d"] < nominal_d * 0.8]
    if not rows:
        return None
    return _mk("thread_mill", max(rows, key=lambda r: r["d"]))


def drill(d: float, depth: float, group: str = "any", tsc: bool = False) -> Tool:
    """Сверло точного диаметра из каталога ZCC с рабочей длиной ≥ глубины: сначала серия для материала
    (алюминий — SC), затем универсальная SU; без внутреннего подвода СОЖ, если на станке нет TSC.
    Самое короткое из подходящих (жёстче), со склада. Нет в каталоге — обобщённое сверло."""
    d = round(d, 2)
    rows = [r for r in catalog_tools() if r["kind"] == "drill" and math.isclose(r["d"], d, abs_tol=0.001)]
    if rows:
        def key(r):
            return (r.get("reach", 0) < depth,  # достаёт
                    bool(r.get("internal_coolant")) and not tsc,  # СОЖ через инструмент — только при TSC
                    not r["in_stock"],  # со склада
                    r["group"] != group,  # серия под материал
                    r["xd"], r["oal"])
        return _cat_tool(sorted(rows, key=key)[0])
    ratio = 5 if depth <= 5 * d else 8 if depth <= 8 * d else 12
    hss = d < 3
    return Tool(
        kind="drill",
        diameter=d,
        flutes=2,
        flute_length=round(d * ratio + d, 1),
        overall_length=round(d * ratio + 40, 0),
        tool_material="HSS-Co" if hss else "твердый сплав",
        coating="TiAlN",
        point_angle=118 if hss else 140,
        description=f"Сверло Ø{_n(d)} {ratio}xD {'HSS-Co 118°' if hss else 'тв. сплав 140°'}",
    )


def reamer(d: float, fit: str, depth: float = 0.0) -> Tool:
    rows = [r for r in catalog_tools() if r["kind"] == "reamer" and math.isclose(r["d"], d, abs_tol=0.001)
            and (not fit or r.get("fit") == fit.upper())]
    if rows:
        r = sorted(rows, key=lambda r: (r.get("reach", 0) < depth, not r["in_stock"], r["oal"]))[0]
        return _cat_tool(r)
    return Tool(kind="reamer", diameter=d, flutes=6, flute_length=round(d * 2 + 10, 0),
                overall_length=round(d * 6 + 50, 0), description=f"Развёртка Ø{_n(d)}{fit} тв. сплав")


TAP_GRIP = 25.0  # зажим метчика в цанге / патроне, мм


@lru_cache(maxsize=1)
def catalog_taps() -> list:
    path = _DIR / "catalogs" / "zcc_taps.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("taps", [])


def tap(size: str, through: bool, depth: float = 0.0, tsc: bool = False) -> Tool:
    """Метчик из каталога ZCC под резьбу, тип отверстия и глубину (рабочая длина l3 ≥ depth).
    Предпочтение: достаёт → со склада → короче (жёстче). Без каталога — обобщённый метчик."""
    d, p = parse_thread(size)
    name = f"M{_n(d)}" + (f"x{_n(p)}" if METRIC_COARSE.get(d, (None,))[0] != p else "")
    hole = "through" if through else "blind"
    cands = [r for r in catalog_taps() if math.isclose(r["d"], d) and math.isclose(r["pitch"], p)
             and r["hole"] == hole and (tsc or not r["internal_coolant"])]
    def reach(r: dict) -> float:
        # DIN 376/374: хвостовик тоньше резьбы и проходит в отверстие — ограничивает общая длина минус зажим
        return r["l1"] - TAP_GRIP if r["shank_d"] < r["d"] - 0.3 else r["l3"]

    if cands:
        r = sorted(cands, key=lambda r: (reach(r) < depth, not r["in_stock"], r["l1"]))[0]
        kind = "сквозная, подточка (B)" if through else "глухая, спираль 40° (C)"
        return Tool(kind="tap", diameter=d, flutes=3, pitch=p, thread=name, tool_material="HSS-E", coating="TiAlN",
                    overall_length=r["l1"], flute_length=r["l2"], reach=reach(r), shank_d=r["shank_d"],
                    article=r["article"], in_stock=r["in_stock"], core_drill=r["core_drill"],
                    description=f"Метчик ZCC {r['article']} ({kind}, DIN {r['shank_din']}, HSS-E HG23)")
    kind = "с подточкой (сквозная)" if through else "спиральная (глухая)"
    return Tool(kind="tap", diameter=d, flutes=3, pitch=p, thread=name,
                tool_material="HSS-E", coating="TiN/TiCN",
                description=f"Метчик машинный {name} {kind}, HSS-E")


def reaming_allowance(d: float) -> float:
    """Припуск под развёртку на диаметр."""
    if d <= 6:
        return 0.15
    if d <= 12:
        return 0.2
    return 0.3
