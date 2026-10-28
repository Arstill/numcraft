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


def end_mills(group: str) -> List[Tool]:
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


def pick_end_mill(group: str, max_d: float, min_lc: float = 0.0, min_d: float = 0.0) -> Optional[Tool]:
    """Наибольшая фреза D ≤ max_d, которая достаёт на глубину (Lc ≥ min_lc); среди равных D — самая короткая.
    Если ни одна не достаёт — наибольшая D с самой длинной режущей частью (риск отметит risks.py)."""
    cands = [t for t in end_mills(group) if min_d - 1e-6 <= t.diameter <= max_d + 1e-6]
    if not cands:
        return None
    fit = [t for t in cands if t.flute_length >= min_lc]
    if fit:
        best_d = max(t.diameter for t in fit)
        return min((t for t in fit if t.diameter == best_d), key=lambda t: t.flute_length)
    best_d = max(t.diameter for t in cands)
    return max((t for t in cands if t.diameter == best_d), key=lambda t: t.flute_length)


def face_mill() -> Tool:
    return _mk("face_mill", _library()["face_mills"][0], coating="пластины для Al / стали")


def ball_mill(max_d: float) -> Optional[Tool]:
    rows = [r for r in _library()["ball_mills"] if r["d"] <= max_d]
    if not rows:
        return None
    row = max(rows, key=lambda r: r["d"])
    t = _mk("ball_mill", row)
    t.corner_radius = t.diameter / 2
    t.description = f"Фреза сферическая Ø{_n(t.diameter)} (R{_n(t.diameter / 2)})"
    return t


def spot_drill() -> Tool:
    return _mk("spot_drill", _library()["spot_drills"][0])


def chamfer_mill() -> Tool:
    return _mk("chamfer_mill", _library()["chamfer_mills"][0])


def thread_mill(nominal_d: float) -> Optional[Tool]:
    rows = [r for r in _library()["thread_mills"] if r["d"] < nominal_d * 0.8]
    if not rows:
        return None
    return _mk("thread_mill", max(rows, key=lambda r: r["d"]))


def drill(d: float, depth: float) -> Tool:
    """Сверло под заданный диаметр: тв. сплав (короткое 5xD или длинное 8xD), до Ø3 — HSS-Co."""
    d = round(d, 2)
    ratio = 5 if depth <= 5 * d else 8 if depth <= 8 * d else 12
    hss = d < 3
    t = Tool(
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
    return t


def reamer(d: float, fit: str) -> Tool:
    return Tool(kind="reamer", diameter=d, flutes=6, flute_length=round(d * 2 + 10, 0),
                overall_length=round(d * 6 + 50, 0), description=f"Развёртка Ø{_n(d)}{fit} тв. сплав")


def tap(size: str, through: bool) -> Tool:
    d, p = parse_thread(size)
    kind = "с подточкой (сквозная)" if through else "спиральная (глухая)"
    return Tool(kind="tap", diameter=d, flutes=3, pitch=p, thread=size.upper().replace("М", "M"),
                tool_material="HSS-E", coating="TiN/TiCN",
                description=f"Метчик машинный {size.upper().replace('М', 'M')} {kind}, HSS-E")


def reaming_allowance(d: float) -> float:
    """Припуск под развёртку на диаметр."""
    if d <= 6:
        return 0.15
    if d <= 12:
        return 0.2
    return 0.3
