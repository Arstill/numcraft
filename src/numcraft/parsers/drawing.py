"""
Разбор чертежа: извлечение текста (PDF с векторным текстом, DXF, TXT) и обозначений.

Распознаётся: Ø с квалитетом (Ø10H7), резьбы (M6, 4×M8-6H), шероховатость (Ra 1.6, √Ra3.2),
общие допуски (ISO 2768-m, ГОСТ 30893.1-m), материал, количество отверстий («4 отв. Ø6.6»).
Растровые сканы (PNG/JPG, PDF без текста) требуют LLM с распознаванием изображений (см. numcraft.llm).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from numcraft.models import HoleFeature, Part, ThreadFeature, _n
from numcraft.parsers.text import DIA, GENTOL_RE, MATERIAL_RE, NUM, THREAD_START

FIT_DIA_RE = re.compile(r"(?:(\d+)\s*(?:отв\.?|[xх×])\s*)?" + DIA + NUM + r"\s*([HНhн]\d{1,2}|[+\-±]\s*\d)?")
THREAD_FULL_RE = re.compile(r"(?:(\d+)\s*(?:отв\.?\s*)?[xх×]?\s*)?" + THREAD_START + NUM +
                            r"(?:\s*[xх×]\s*(\d+(?:[.,]\d+)?))?(?:\s*-\s*\d[HgGh])?")
RA_RE = re.compile(r"(?:Ra|√)\s*(\d+(?:[.,]\d+)?)")
UNSUPPORTED_MAT_RE = re.compile(r"\b(Д16Т?|АМг\d|12Х18Н10Т|AISI\s*30[34]|40Х|ст\.?\s*3|2024|6082|5083)\b", re.IGNORECASE)


@dataclass
class DrawingInfo:
    source: str = ""
    text: str = ""
    material: Optional[str] = None
    unsupported_material: Optional[str] = None
    general_tolerance: Optional[str] = None
    fits: List[Tuple[float, str, int]] = field(default_factory=list)  # (Ø, квалитет, кол-во)
    threads: List[Tuple[str, int]] = field(default_factory=list)  # ("M6", кол-во)
    ra_values: List[float] = field(default_factory=list)
    diameters: List[Tuple[float, int]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    converted: List[str] = field(default_factory=list)  # резьбы, заменившие отверстия модели


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def read_pdf_text(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def read_dxf_text(path: str) -> str:
    """Текст из DXF: TEXT/MTEXT (код 1) и фактические размеры DIMENSION (код 42)."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    pairs = list(zip(raw[0::2], raw[1::2]))
    out: List[str] = []
    entity = None
    for code, val in pairs:
        code = code.strip()
        if code == "0":
            entity = val.strip()
            continue
        if entity in ("TEXT", "MTEXT", "ATTRIB") and code in ("1", "3"):
            v = re.sub(r"\\[A-Za-z][^;]*;|\\P|[{}]", " ", val)
            v = v.replace("%%c", "Ø").replace("%%C", "Ø").replace("%%d", "°").replace("%%p", "±")
            out.append(v.strip())
        elif entity == "DIMENSION" and code == "1" and val.strip() not in ("", "<>"):
            out.append(val.replace("<>", "").replace("%%c", "Ø").strip())
        elif entity == "DIMENSION" and code == "42":
            out.append(f"[размер {round(float(val), 3)}]")
    return "\n".join(o for o in out if o)


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return read_pdf_text(path)
    if ext == ".dxf":
        return read_dxf_text(path)
    if ext in (".txt", ".md"):
        return Path(path).read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Формат {ext} не читается напрямую — для сканов и изображений используйте LLM-режим.")


def parse_notation(text: str, source: str = "") -> DrawingInfo:
    info = DrawingInfo(source=source, text=text)
    t = text.replace("⌀", "Ø").replace("∅", "Ø")
    if m := MATERIAL_RE.search(t):
        info.material = m.group(0)
    elif m := UNSUPPORTED_MAT_RE.search(t):
        info.unsupported_material = m.group(1)
        info.warnings.append(f"Материал {m.group(1)} вне MVP (6061, 7075, сталь 45/1045) — режимы не рассчитаны.")
    if m := GENTOL_RE.search(t):
        info.general_tolerance = m.group(1).upper()
    for m in FIT_DIA_RE.finditer(t):
        cnt = int(m.group(1)) if m.group(1) else 1
        d = _f(m.group(2))
        fit = (m.group(3) or "").replace("Н", "H").replace("н", "h").upper()
        if fit.startswith("H"):
            info.fits.append((d, fit, cnt))
        info.diameters.append((d, cnt))
    for m in THREAD_FULL_RE.finditer(t):
        cnt = int(m.group(1)) if m.group(1) else 1
        size = "M" + m.group(2).replace(",", ".") + (f"x{m.group(3).replace(',', '.')}" if m.group(3) else "")
        info.threads.append((size, cnt))
    info.ra_values = sorted({_f(x) for x in RA_RE.findall(t)})
    if not t.strip():
        info.warnings.append("В файле нет текстового слоя (скан?) — нужен LLM-режим с изображением.")
    return info


def analyze_drawing(path: str) -> DrawingInfo:
    return parse_notation(extract_text(path), source=path)


def apply_to_part(part: Part, info: DrawingInfo) -> List[str]:
    """Дополнить Part данными чертежа: квалитеты, резьбы вместо отверстий под метчик, общий допуск."""
    from numcraft.knowledge.tooling import parse_thread, tap_drill

    notes: List[str] = []
    if info.general_tolerance and not part.general_tolerance:
        part.general_tolerance = info.general_tolerance
    holes = [f for f in part.features if isinstance(f, HoleFeature)]
    for d, fit, _ in info.fits:
        hit = [h for h in holes if abs(h.diameter - d) < 0.05]
        for h in hit:
            h.fit = fit
        notes.append(f"Ø{_n(d)}{fit}: " + (f"применён к {len(hit)} отв." if hit else "в модели не найден"))
    for size, cnt in info.threads:
        try:
            d, p = parse_thread(size)
        except ValueError as e:
            notes.append(str(e))
            continue
        drill = tap_drill(d, p)
        hit = [h for h in holes if abs(h.diameter - drill) < 0.06 or abs(h.diameter - d) < 0.06]
        if not hit:
            notes.append(f"{size}: отверстие в модели не найдено — добавьте резьбу вручную.")
            continue
        for h in hit:
            idx = part.features.index(h)
            # в модели (Hole Wizard) глубина отверстия — это глубина сверла; резьба короче на заборную часть
            thread_len = None if h.through or not h.depth else round(max(h.depth - 3 * p, 1.5 * d), 2)
            part.features[idx] = ThreadFeature(
                id=h.id, side=h.side, size=size, depth=thread_len, through=h.through,
                count=h.count, positions=h.positions, z_start=h.z_start,
                note="из чертежа; длина резьбы = глубина отверстия модели − 3P (уточнить)")
            holes.remove(h)
        info.converted.append(size)
        notes.append(f"{size}: {sum(x.count for x in hit)} отв. Ø{_n(hit[0].diameter)} заменены на резьбу.")
    if info.ra_values:
        notes.append(f"Шероховатость на чертеже: Ra {', '.join(_n(r) for r in info.ra_values)} "
                     f"(минимальная Ra {_n(min(info.ra_values))} — чистовые проходы).")
    return notes + info.warnings
