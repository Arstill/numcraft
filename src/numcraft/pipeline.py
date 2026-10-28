"""
Сборка входных данных (текст / STEP / чертёж / JSON) в Part и расчёт техкарты.

Приоритет источников: JSON (Part) > STEP (геометрия) > текст. Чертёж дополняет:
квалитеты, резьбы, общий допуск, материал.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from numcraft import model3d
from numcraft.gcode import generate
from numcraft.knowledge.machine import load_machine
from numcraft.knowledge.materials import UnknownMaterial, resolve_material
from numcraft.models import Part, TechSheet
from numcraft.parsers import drawing as drw
from numcraft.parsers import step as stp
from numcraft.parsers.text import parse_description
from numcraft.planner import plan_part


class InputError(ValueError):
    """Недостаточно данных: список вопросов к пользователю."""

    def __init__(self, missing: List[str]):
        self.missing = missing
        super().__init__("Не хватает данных: " + "; ".join(missing))


@dataclass
class Inputs:
    text: Optional[str] = None
    step_path: Optional[str] = None
    drawing_path: Optional[str] = None
    part_json: Optional[str] = None  # путь к .json или сама строка JSON
    material: Optional[str] = None
    name: Optional[str] = None
    stock: Optional[List[float]] = None


@dataclass
class Result:
    sheet: TechSheet
    source_notes: List[str] = field(default_factory=list)
    step_summary: Optional[str] = None


def build_part(inp: Inputs) -> tuple[Part, List[str], Optional[str], Optional[stp.StepAnalysis]]:
    notes: List[str] = []
    missing: List[str] = []
    step_summary = None
    analysis = None
    part: Optional[Part] = None
    info = drw.analyze_drawing(inp.drawing_path) if inp.drawing_path else None

    material = inp.material or (info.material if info else None)

    if inp.part_json:
        raw = Path(inp.part_json).read_text(encoding="utf-8") if not inp.part_json.lstrip().startswith("{") \
            else inp.part_json
        part = Part.model_validate(json.loads(raw))
        if material:
            part.material = material
    elif inp.step_path:
        analysis = stp.analyze_step_file(inp.step_path)
        step_summary = stp.summary_ru(analysis)
        pr = parse_description(inp.text, material=material) if inp.text else None
        mat = material or (pr.material if pr else None)
        if not mat:
            raise InputError(["материал (6061, 7075, сталь 45 или 1045) — в STEP его нет"])
        prod = analysis.product
        default_name = prod if prod and "translator" not in prod.lower() else Path(inp.step_path).stem
        part, n = stp.to_part(analysis, mat, name=inp.name or default_name)
        notes += n
        if pr:
            # из текста берём то, чего геометрия не даёт: резьбы, фаски, 3D, контур с допуском
            keep = [f for f in pr.features if f.type in ("thread", "chamfer", "surface3d", "contour", "face")]
            part.features += keep
            if keep:
                notes.append(f"Из описания добавлено: {', '.join(f.type for f in keep)}.")
    elif inp.text:
        pr = parse_description(inp.text, material=material)
        if pr.unparsed:
            notes.append("Не распознано в описании: " + " | ".join(pr.unparsed))
        if pr.part is None:
            raise InputError(pr.missing)
        missing += [m for m in pr.missing]
        part = pr.part
    else:
        raise InputError(["описание детали, STEP или JSON"])

    try:
        part.material = resolve_material(part.material).name
    except UnknownMaterial as e:
        raise InputError([str(e)])
    if inp.name:
        part.name = inp.name
    if inp.stock:
        from numcraft.models import Box
        part.stock = Box(x=inp.stock[0], y=inp.stock[1], z=inp.stock[2])
    if info:
        dnotes = drw.apply_to_part(part, info)
        notes = [n for n in notes if not any(f"под метчик {sz}:" in n for sz in info.converted)] + dnotes
    notes += [f"Допущение при разборе: {m}" for m in missing]
    return part, notes, step_summary, analysis


def run(inp: Inputs, gcode: bool = False, dialect: str = "fanuc", max_rpm: Optional[int] = None) -> Result:
    part, notes, step_summary, analysis = build_part(inp)
    machine = load_machine(max_rpm=max_rpm)
    sheet = plan_part(part, machine)
    sheet.assumptions = notes + sheet.assumptions
    if analysis is not None:
        origin = (analysis.bbox_min[0], analysis.bbox_min[1], analysis.bbox_max[2])
        sheet.model3d = model3d.build(sheet, analysis.edges, origin)
    else:
        sheet.model3d = model3d.build(sheet)
    if gcode:
        sheet.gcode = generate(sheet, dialect=dialect)  # type: ignore[arg-type]
    return Result(sheet=sheet, source_notes=notes, step_summary=step_summary)
