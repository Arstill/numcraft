"""
Стратегии HSMWorks и их ключевые параметры.

Названия стратегий и полей — как в интерфейсе HSMWorks (англ.), рядом пояснение на русском,
чтобы технолог нашёл поле в любой локализации.
"""
from __future__ import annotations

import math
from typing import Dict

from numcraft.knowledge.materials import Material
from numcraft.models import CuttingData, Tool, _n

FACE = "Face (торцевание)"
ADAPTIVE_2D = "2D Adaptive Clearing (адаптивная выборка)"
POCKET_2D = "2D Pocket (карман)"
CONTOUR_2D = "2D Contour (контур)"
SLOT = "Slot (паз)"
BORE = "Bore (спиральная расточка)"
CIRCULAR = "Circular (круговой)"
THREAD = "Thread (резьбофрезерование)"
CHAMFER_2D = "2D Contour — Chamfer (фаска)"
DRILL = "Drill (сверление)"
ADAPTIVE_3D = "Adaptive Clearing 3D (адаптивная черновая)"
PARALLEL_3D = "Parallel (параллельная)"
SCALLOP_3D = "Scallop (постоянный гребешок)"
STEEP_SHALLOW_3D = "Steep and Shallow (крутые/пологие)"

# Типы циклов Drill в HSMWorks → код FANUC
DRILL_CYCLES = {
    "G81": "Drilling – rapid out",
    "G82": "Counterboring – dwell and rapid out",
    "G73": "Chip breaking – partial retract",
    "G83": "Deep drilling – full retract",
    "G84": "Tapping (жёсткое)",
    "G85": "Reaming – feed out",
}


def face(tool: Tool, cd: CuttingData, total: float, finish_ap: float) -> Dict[str, str]:
    p = {
        "Max stepover (макс. шаг)": f"{_n(round(tool.diameter * 0.7, 1))} мм (70 % D)",
        "Stock offset (выход за заготовку)": f"{_n(round(tool.diameter * 0.5 + 3, 0))} мм",
        "Direction": "Climb (попутное)",
    }
    if total > finish_ap * 2:
        stepdown = min(cd.ap or total, round(total - finish_ap, 2))
        p["Multiple depths (несколько проходов)"] = (
            f"вкл.: Max stepdown {_n(stepdown)} мм, Finishing stepdown {_n(finish_ap)} мм"
        )
    p["Stock to leave (припуск)"] = "0"
    return p


def adaptive(tool: Tool, cd: CuttingData, mat: Material, depth: float, rest: bool = False,
             stock_contours: bool = False) -> Dict[str, str]:
    m = mat.milling
    stepdown = min(cd.ap or depth, depth)
    p = {
        "Optimal load (оптимальная нагрузка)": f"{_n(cd.ae or 0)} мм ({round((cd.ae or 0) / tool.diameter * 100)} % D)",
        "Maximum roughing stepdown (шаг по Z)": f"{_n(stepdown)} мм",
        "Fine stepdown (промежуточные слои)": f"{_n(round(stepdown / 4, 1))} мм" if stepdown > 6 else "—",
        "Stock to leave (припуск)": f"радиальный {_n(m['leave_radial'])} / осевой {_n(m['leave_axial'])} мм",
        "Ramp type (врезание)": f"Helix, угол {m['ramp_angle_deg']}°, диаметр ≈ {_n(round(tool.diameter * 0.9, 1))} мм",
        "Minimum cutting radius": f"{_n(round(tool.diameter * 0.1, 1))} мм",
        "Feed optimization": "вкл., снижение в углах 0.7",
    }
    if stock_contours:
        p["Stock contours (контур заготовки)"] = "выбрать контур заготовки — врезание снаружи, без спирали"
    if rest:
        p["Rest machining (дообработка)"] = "вкл., from previous operation(s)"
    return p


def pocket(tool: Tool, cd: CuttingData, floor_only: bool = False) -> Dict[str, str]:
    p = {
        "Maximum stepover (шаг)": f"{_n(cd.ae or round(tool.diameter * 0.5, 1))} мм",
        "Ramp type": "Helix 2°",
    }
    if floor_only:
        p["Multiple depths"] = "выкл. — только чистовой проход по дну"
        p["Stock to leave"] = "радиальный 0.05 / осевой 0 мм (стенки — следующей операцией 2D Contour)"
    else:
        p["Maximum stepdown"] = f"{_n(cd.ap or 0)} мм"
    return p


def contour_finish(tool: Tool, cd: CuttingData, depth: float, tolerance: float | None) -> Dict[str, str]:
    p = {
        "Stock to leave (припуск)": "0",
        "Finishing passes": "1" + (" + Spring pass (зачистной)" if tolerance and tolerance <= 0.03 else ""),
        "Compensation type (коррекция)": (
            "Wear (по износу, D-корректор на стойке = 0)" if tolerance and tolerance <= 0.05 else "In computer"
        ),
        "Lead-in / Lead-out": f"дуга R{_n(round(tool.diameter * 0.3, 1))} мм, касательный вход",
        "Direction": "Climb (попутное)",
    }
    if depth > tool.flute_length > 0:
        p["Multiple depths"] = f"вкл., шаг ≤ {_n(tool.flute_length - 1)} мм (глубина больше Lc)"
    else:
        p["Multiple depths"] = "выкл. — вся высота стенки за проход"
    return p


def contour_light_rough(tool: Tool, allowance: float) -> Dict[str, str]:
    return {
        "Multiple finishing passes": f"2 прохода, шаг {_n(round(max(allowance - 0.2, 0.1), 2))} мм",
        "Stock to leave": "0",
        "Compensation type": "In computer",
    }


def slot(tool: Tool, cd: CuttingData) -> Dict[str, str]:
    return {
        "Multiple depths": f"вкл., Max stepdown {_n(cd.ap or 0)} мм",
        "Ramp (врезание)": "Ramp / Zig-zag 2°",
        "Stock to leave": "0",
    }


def bore(tool: Tool, cd: CuttingData, hole_d: float, finish: bool, mat: Material) -> Dict[str, str]:
    pitch = round(tool.diameter * (0.08 if mat.is_aluminum else 0.04), 2)
    return {
        "Pitch (шаг спирали)": f"{_n(pitch)} мм/виток",
        "Finishing passes": "вкл., Spring pass" if finish else "выкл.",
        "Stock to leave": "0" if finish else "радиальный 0.2 мм",
        "Compensation": "Wear (по износу)" if finish else "In computer",
        "Диаметр отверстия": f"Ø{_n(hole_d)}",
    }


def drill(cycle: str, depth_note: str, peck: float | None, through: bool) -> Dict[str, str]:
    p = {
        "Cycle type (цикл)": f"{DRILL_CYCLES[cycle]} ({cycle})",
        "Bottom height": depth_note,
        "Retract height (R)": "Z+2 мм от верха",
    }
    if peck:
        p["Pecking depth (Q)"] = f"{_n(peck)} мм"
    if through:
        p["Drill tip through bottom"] = "вкл., Break-through depth 1 мм"
    return p


def tapping(pitch: float, depth_note: str) -> Dict[str, str]:
    return {
        "Cycle type (цикл)": "Tapping (G84), жёсткое нарезание",
        "Pitch (шаг)": f"{_n(pitch)} мм",
        "Bottom height": depth_note,
        "Retract height (R)": "Z+5 мм (≥ 3 шагов над поверхностью)",
    }


def reaming(depth_note: str) -> Dict[str, str]:
    return {
        "Cycle type (цикл)": "Reaming – feed out (G85)",
        "Bottom height": depth_note,
        "Retract height (R)": "Z+2 мм",
    }


def thread_mill(pitch: float, depth: float) -> Dict[str, str]:
    return {
        "Pitch (шаг)": f"{_n(pitch)} мм",
        "Thread depth / Bottom": f"{_n(depth)} мм",
        "Right-handed": "да (правая), снизу вверх попутно",
        "Number of stepovers": "2 (сталь) / 1 (алюминий)",
        "Compensation": "Wear — подгонка калибр-пробкой",
    }


def chamfer(size: float, tool: Tool) -> Dict[str, str]:
    return {
        "Chamfer width (ширина фаски)": f"{_n(size)} мм",
        "Chamfer tip offset (смещение вершины)": "0.5 мм",
        "Chamfer clearance": "0.5 мм",
        "Tool": f"фасочная Ø{_n(tool.diameter)} {_n(tool.point_angle or 90)}°",
    }


def scallop_stepover(ball_r: float, ra_um: float) -> float:
    """Шаг по высоте гребешка h ≈ 4·Ra (мкм→мм): ae = 2·√(2·R·h − h²)."""
    h = 4 * ra_um / 1000
    return round(2 * math.sqrt(max(2 * ball_r * h - h * h, 1e-9)), 2)
