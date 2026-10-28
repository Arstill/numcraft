"""
Расчёт режимов резания под конкретный станок.

n = 1000·Vc / (π·D), ограничение по оборотам шпинделя; Vf = fz·z·n, ограничение по подаче станка;
утонение стружки при ae < D/2; мощность Pc = ap·ae·Vf·kc / 60·10⁶ против кривой момента шпинделя.
"""
from __future__ import annotations

import math
from typing import Optional

from numcraft.knowledge.machine import Machine
from numcraft.knowledge.materials import Material
from numcraft.models import CuttingData, Tool, _n

# Ограничение оборотов при жёстком нарезании резьбы (запас по реверсу шпинделя VF-2)
TAP_MAX_RPM = 2000


def chip_thinning_factor(d: float, ae: float, cap: float) -> float:
    if ae <= 0 or ae >= d / 2:
        return 1.0
    return min(cap, d / (2 * math.sqrt(ae * (d - ae))))


def _rpm(vc: float, d: float, machine: Machine, limits: list) -> int:
    n = vc * 1000 / (math.pi * d)
    if n > machine.spindle.max_rpm:
        limits.append(f"обороты шпинделя {machine.spindle.max_rpm} (расчётные {round(n)})")
        n = machine.spindle.max_rpm
    return int(round(max(n, machine.spindle.min_rpm)))


def _feed(vf: float, machine: Machine, limits: list) -> float:
    if vf > machine.max_cutting_feed_mm_min:
        limits.append(f"макс. рабочая подача {machine.max_cutting_feed_mm_min} мм/мин")
        return machine.max_cutting_feed_mm_min
    return vf


def _actual_vc(rpm: int, d: float) -> float:
    return round(math.pi * d * rpm / 1000, 0)


def _check_power(cd: CuttingData, d: float, material: Material, machine: Machine) -> CuttingData:
    """Если не хватает мощности — уменьшаем ap."""
    if not (cd.ap and cd.ae):
        return cd
    pc = cd.ap * cd.ae * cd.feed * material.kc / 60e6
    avail = machine.available_power_kw(cd.rpm)
    if pc > avail:
        scale = avail / pc
        cd.ap = round(cd.ap * scale, 2)
        pc = avail
        cd.limits.append(f"мощность шпинделя на {cd.rpm} об/мин (~{avail:.1f} кВт) — ap уменьшен")
    cd.power_kw = round(pc, 2)
    return cd


def milling(tool: Tool, material: Material, machine: Machine, op: str,
            ap: Optional[float] = None, ae: Optional[float] = None) -> CuttingData:
    """
    op: adaptive | slot | pocket | finish_wall | finish_floor | contour | bore | chamfer | ball | thread_mill
    ap/ae по умолчанию — из базы материала (доли диаметра).
    """
    m = material.milling
    d = tool.diameter
    z = max(tool.flutes, 1)
    limits: list = []
    fz = min(max(m["fz_k"] * d, m["fz_min"]), m["fz_max"])
    cap = m["chip_thinning_max"]

    if op == "adaptive":
        vc = m["vc"]["adaptive"]
        ae = ae or round(m["adaptive_ae"] * d, 2)
        ap = ap or round(m["adaptive_ap"] * d, 1)
        fz *= chip_thinning_factor(d, ae, cap)
    elif op == "slot":
        vc = m["vc"]["slot"]
        ae = d
        ap = ap or round(m["slot_ap"] * d, 1)
        fz *= 0.75
    elif op == "pocket":
        vc = m["vc"]["pocket"]
        ae = ae or round(m["pocket_ae"] * d, 2)
        ap = ap or round(m["pocket_ap"] * d, 1)
        fz *= chip_thinning_factor(d, ae, cap)
    elif op == "bore":
        vc = m["vc"]["pocket"]
        fz *= 0.7
    elif op == "finish_wall":
        vc = m["vc"]["finish"]
        ae = ae or m["finish_ae_mm"]
        fz *= 0.8 * chip_thinning_factor(d, ae, 1.3)
    elif op == "finish_floor":
        vc = m["vc"]["finish"]
        ap = ap or m["leave_axial"]
        ae = ae or round(0.6 * d, 2)
        fz *= 0.8
    elif op == "contour":
        vc = m["vc"]["contour"]
    elif op == "chamfer":
        vc = material.chamfer_mill["vc"]
        fz = material.chamfer_mill["fz"]
        d = max(d * 0.5, 3.0)  # эффективный диаметр в зоне фаски
    elif op == "ball":
        vc = material.ball_mill["vc"]
        fz = material.ball_mill["fz_k"] * d
    elif op == "thread_mill":
        vc = material.thread_mill["vc"]
        fz = material.thread_mill["fz"]
    else:
        raise ValueError(f"Неизвестный класс операции {op}")

    if ap and tool.flute_length and ap > tool.flute_length and tool.kind != "face_mill":
        ap = tool.flute_length
        limits.append(f"ap ограничен длиной режущей части Lc={_n(tool.flute_length)}")

    rpm = _rpm(vc, d, machine, limits)
    feed = _feed(fz * z * rpm, machine, limits)
    cd = CuttingData(
        vc=_actual_vc(rpm, d), rpm=rpm, feed=round(feed), fz=round(feed / (z * rpm), 4),
        ap=ap, ae=ae, plunge_feed=round(feed * (0.5 if op == "adaptive" else 0.3)),
        coolant=material.coolant, limits=limits,
    )
    return _check_power(cd, tool.diameter, material, machine)


def face_milling(tool: Tool, material: Material, machine: Machine, ap: float, width: float) -> CuttingData:
    p = material.face_mill
    limits: list = []
    rpm = _rpm(p["vc"], tool.diameter, machine, limits)
    feed = _feed(p["fz"] * tool.flutes * rpm, machine, limits)
    ae = round(min(width, 0.7 * tool.diameter), 1)
    cd = CuttingData(vc=_actual_vc(rpm, tool.diameter), rpm=rpm, feed=round(feed),
                     fz=round(feed / (tool.flutes * rpm), 3), ap=round(ap, 2), ae=ae,
                     coolant=material.coolant, limits=limits)
    return _check_power(cd, tool.diameter, material, machine)


def drilling(tool: Tool, material: Material, machine: Machine) -> CuttingData:
    p = material.drill
    d = tool.diameter
    limits: list = []
    if tool.tool_material.startswith("HSS"):
        vc, f = p["vc_hss"], p["f_k"] * d * 0.6
    else:
        vc, f = p["vc"], min(p["f_k"] * d, p["f_max"])
    rpm = _rpm(vc, d, machine, limits)
    feed = _feed(f * rpm, machine, limits)
    vc_act = _actual_vc(rpm, d)
    pc = f * vc_act * d * material.kc / 240e3
    avail = machine.available_power_kw(rpm)
    if pc > avail:
        limits.append(f"мощность (~{pc:.1f} из {avail:.1f} кВт)")
    return CuttingData(vc=vc_act, rpm=rpm, feed=round(feed), f_rev=round(feed / rpm, 3),
                       power_kw=round(pc, 2), coolant=material.coolant, limits=limits)


def spot_drilling(tool: Tool, material: Material, machine: Machine) -> CuttingData:
    p = material.spot_drill
    limits: list = []
    rpm = _rpm(p["vc"], tool.diameter, machine, limits)
    feed = _feed(p["f_rev"] * rpm, machine, limits)
    return CuttingData(vc=_actual_vc(rpm, tool.diameter), rpm=rpm, feed=round(feed),
                       f_rev=p["f_rev"], coolant=material.coolant, limits=limits)


def tapping(tool: Tool, material: Material, machine: Machine) -> CuttingData:
    limits: list = []
    rpm = _rpm(material.tap["vc"], tool.diameter, machine, limits)
    if rpm > TAP_MAX_RPM:
        limits.append(f"обороты при жёстком нарезании резьбы ≤ {TAP_MAX_RPM}")
        rpm = TAP_MAX_RPM
    feed = round(rpm * (tool.pitch or 1.0), 2)
    return CuttingData(vc=_actual_vc(rpm, tool.diameter), rpm=rpm, feed=feed, f_rev=tool.pitch,
                       coolant=material.coolant + "; для стали — масляная эмульсия/паста", limits=limits)


def reaming(tool: Tool, material: Material, machine: Machine) -> CuttingData:
    p = material.reamer
    limits: list = []
    rpm = _rpm(p["vc"], tool.diameter, machine, limits)
    f = p["f_k"] * tool.diameter
    feed = _feed(f * rpm, machine, limits)
    return CuttingData(vc=_actual_vc(rpm, tool.diameter), rpm=rpm, feed=round(feed),
                       f_rev=round(f, 3), fz=round(f / tool.flutes, 4), coolant=material.coolant, limits=limits)
