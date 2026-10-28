"""
Разбор русского описания детали в модель Part.

Пример:
  «Плита 120х80х20, алюминий 6061. Карман 60х40 глубина 8 R5 в центре.
   4 отв. Ø6.6 сквозные по углам с отступом 10. 2 резьбы М6 гл. 12 в точках (30;40), (90;40).
   Отверстие Ø10H7 сквозное в центре. Фаска 0.5 по контуру.»

Детерминированный разбор покрывает типовые формулировки; всё, что не распознано, возвращается
в `unparsed` (передаётся LLM или технологу).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from numcraft.knowledge.materials import UnknownMaterial, resolve_material
from numcraft.models import (
    Box, ChamferFeature, ContourFeature, Counterbore, FaceFeature, HoleFeature, Part, PocketFeature,
    SlotFeature, SurfaceFeature, ThreadFeature,
)

NUM = r"(\d+(?:[.,]\d+)?)"
X = r"\s*[xх×*]\s*"
DIA = r"(?:[Øø⌀Ф]|диам(?:етр(?:ом)?|\.)?)\s*"

MATERIAL_RE = re.compile(
    r"(?:сталь|стали|ст\.?)\s*45|c45|ck45|aisi\s*1045|\b1045\b|6061(?:\s*-?\s*t6)?|7075(?:\s*-?\s*t6)?|ад33|в95(?:т1)?",
    re.IGNORECASE,
)
SIZE3_RE = re.compile(NUM + X + NUM + X + NUM)
SIZE2_RE = re.compile(NUM + X + NUM + r"(?:" + X + NUM + r")?")
DEPTH_RE = re.compile(r"(?:глуб\w*\.?|гл\.?|на\s+глубину)\s*" + NUM, re.IGNORECASE)
THROUGH_RE = re.compile(r"сквозн|насквозь|на\s+проход", re.IGNORECASE)
DIA_RE = re.compile(DIA + NUM, re.IGNORECASE)
FIT_RE = re.compile(r"(?<=\d)\s*([HН]\s?\d{1,2})\b")
THREAD_START = r"(?:(?<=[\s\dxх×(,])|^)[MМ]\s?"
THREAD_RE = re.compile(THREAD_START + NUM + r"(?:\s*[xх×]\s*" + NUM + r")?")
RADIUS_RE = re.compile(r"(?:\b[RР]\s?|радиус\w*\s*)" + NUM)
TOL_RE = re.compile(r"±\s?" + NUM)
RA_RE = re.compile(r"\bRa\s?" + NUM, re.IGNORECASE)
COUNT_RE = re.compile(r"(?:^|\s)(\d+)\s*(?:шт\.?\s*)?(?=(?:отв|резьб|паз|карман|выборк|окн|[xх×]\s*[ØøМM⌀]|[ØøМM⌀]))",
                      re.IGNORECASE)
POINT_RE = re.compile(r"\(\s*(-?\d+(?:[.,]\d+)?)\s*[;,]\s*(-?\d+(?:[.,]\d+)?)\s*\)")
XY_RE = re.compile(r"\bX\s?(-?\d+(?:[.,]\d+)?)\s*,?\s*Y\s?(-?\d+(?:[.,]\d+)?)", re.IGNORECASE)
CORNERS_RE = re.compile(r"по\s+углам(?:\D{0,30}?" + NUM + r")?", re.IGNORECASE)
CENTER_RE = re.compile(r"в\s+центре|по\s+центру|центральн", re.IGNORECASE)
QTY_RE = re.compile(r"(?:парти[яи]|кол(?:-во|ичество)|тираж)\D{0,12}(\d+)", re.IGNORECASE)
GENTOL_RE = re.compile(r"(ISO\s*2768\s*-?\s*[fmcv]\w?|ГОСТ\s*30893\.1\s*-?\s*[fmcvтсгочн]\w?)", re.IGNORECASE)
COUNTERBORE_RE = re.compile(r"цековк\w*\s*" + DIA + NUM + r"(?:" + X + r"|\s*(?:гл\w*\.?|глубин\w*)\s*)" + NUM,
                            re.IGNORECASE)
CHAMFER_RE = re.compile(r"фаск\w*\s*" + NUM + r"|" + NUM + r"\s*[xх×]\s*45", re.IGNORECASE)

SIDE_PATTERNS = [
    ("bottom", r"снизу|с\s+обратн|с\s+нижн|\bниз\b|сторона\s*[bб]\b"),
    ("front", r"спереди|передн\w*\s+гран|сбоку|боков"),
    ("back", r"сзади|задн\w*\s+гран"),
    ("left", r"слева|лев\w*\s+гран"),
    ("right", r"справа|прав\w*\s+гран"),
]

KEYWORDS = {
    "thread": re.compile(r"резьб|" + THREAD_START + r"\d"),
    "pocket": re.compile(r"карман|выборк|\bокн", re.IGNORECASE),
    "slot": re.compile(r"\bпаз", re.IGNORECASE),
    "hole": re.compile(r"отв|отверст|" + DIA + r"\d", re.IGNORECASE),
    "chamfer": re.compile(r"фаск|притуп", re.IGNORECASE),
    "face": re.compile(r"торц(?:ев|ов)", re.IGNORECASE),
    "surface3d": re.compile(r"3d|3д|поверхност|сфер|скульпт|радиусн\w+\s+переход", re.IGNORECASE),
    "contour": re.compile(r"наружн\w*\s+контур|контур\w*\s+(?:детали|с\s+допуск)", re.IGNORECASE),
}
FEATURE_ORDER = ["thread", "pocket", "slot", "hole", "chamfer", "surface3d", "face", "contour"]


def _f(s: str) -> float:
    return float(s.replace(",", "."))


@dataclass
class ParseResult:
    part: Optional[Part]
    features: list = field(default_factory=list)
    material: Optional[str] = None  # найденная марка (как в тексте)
    missing: List[str] = field(default_factory=list)
    unparsed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


ABBREVIATIONS = {"гл", "отв", "глуб", "шт", "диам", "ст", "мм", "см", "рис", "п", "т", "max", "min"}


def _split_sentences(text: str) -> List[str]:
    """Деление по «. » с учётом сокращений («гл. 12», «отв. Ø6»)."""
    out, start = [], 0
    for m in re.finditer(r"\.\s+", text):
        prev = re.search(r"([A-Za-zА-Яа-яЁё]+)$", text[start:m.start()])
        nxt = text[m.end():m.end() + 1]
        if prev and prev.group(1).lower() in ABBREVIATIONS:
            continue
        if nxt and (nxt.isupper() or nxt.isdigit()):
            out.append(text[start:m.start()])
            start = m.end()
    out.append(text[start:])
    return out


def _segments(text: str) -> List[str]:
    # запятые внутри скобок (координаты) не должны резать фразу
    text = re.sub(r"\(([^)]*)\)", lambda m: "(" + m.group(1).replace(",", ";") + ")", text)
    raw = [p for sent in _split_sentences(text) for p in re.split(r"[;:\n]+|,\s+", sent)]
    # «… с карманом 50х30х6 и 3D поверхностью …» — делим по «и», если обе части — признаки
    split: List[str] = []
    for r in raw:
        parts = re.split(r"\s+(?:и|а\s+также|плюс)\s+", r)
        if len(parts) > 1 and all(_kind(p) or SIZE3_RE.search(p) for p in parts):
            split += parts
        else:
            split.append(r)
    segs: List[str] = []
    for r in (s.strip(" .,") for s in split):
        if not r:
            continue
        if segs and _kind(r) is None and not SIZE3_RE.search(r) and not MATERIAL_RE.search(r) \
                and not QTY_RE.search(r) and _kind(segs[-1]) is not None:
            segs[-1] += ", " + r  # хвост предыдущего признака: «…, R5», «…, сквозные»
        else:
            segs.append(r)
    return segs


def _kind(seg: str) -> Optional[str]:
    if COUNTERBORE_RE.search(seg) and not KEYWORDS["hole"].search(COUNTERBORE_RE.sub("", seg)):
        return None
    for k in FEATURE_ORDER:
        if KEYWORDS[k].search(seg):
            if k == "hole" and KEYWORDS["thread"].search(seg):
                return "thread"
            return k
    return None


def _side(seg: str) -> str:
    for side, pat in SIDE_PATTERNS:
        if re.search(pat, seg, re.IGNORECASE):
            return side
    return "top"


def _count(seg: str) -> int:
    m = COUNT_RE.search(seg)
    return int(m.group(1)) if m else 1


def _points(seg: str) -> List[Tuple[float, float]]:
    pts = [(_f(a), _f(b)) for a, b in POINT_RE.findall(seg)]
    pts += [(_f(a), _f(b)) for a, b in XY_RE.findall(seg)]
    return pts


def parse_description(text: str, material: Optional[str] = None) -> ParseResult:
    res = ParseResult(part=None)
    segs = _segments(text)
    size: Optional[Box] = None
    stock: Optional[Box] = None
    name = None
    qty = 1
    gentol = None
    feats = []
    deferred_positions = []  # (feature, kind) — «по углам», «в центре» считаем после габарита

    mat_text = material
    if not mat_text:
        m = MATERIAL_RE.search(text)
        if m:
            mat_text = m.group(0)
        elif re.search(r"\bалюмин|\bдюрал", text, re.IGNORECASE):
            res.missing.append("марка алюминия (6061 или 7075)")
        elif re.search(r"\bстал", text, re.IGNORECASE):
            res.missing.append("марка стали (45 / 1045)")
        else:
            res.missing.append("материал")
    if m := QTY_RE.search(text):
        qty = int(m.group(1))
    if m := GENTOL_RE.search(text):
        gentol = m.group(1).upper().replace("  ", " ")

    for seg in segs:
        kind = _kind(seg)
        low = seg.lower()
        m3 = SIZE3_RE.search(seg)
        kw = KEYWORDS[kind].search(seg) if kind else None
        if m3 and (kind is None or (kw and m3.start() < kw.start())):
            # габарит/заготовка, в т.ч. «Деталь 50х50х10 с отверстием Ø5»
            box = Box(x=_f(m3.group(1)), y=_f(m3.group(2)), z=_f(m3.group(3)))
            if "заготов" in low[:m3.start() + 1]:
                stock = box
            elif size is None:
                size = box
                word = re.match(r"\s*([А-Яа-яЁё][А-Яа-яЁё\-]+)", seg)
                if word and not MATERIAL_RE.search(word.group(1)):
                    name = word.group(1).capitalize()
            if kind is None:
                continue
            seg = seg[:m3.start()] + seg[m3.end():]
            low = seg.lower()
        if kind is None:
            if not (MATERIAL_RE.search(seg) or QTY_RE.search(seg) or GENTOL_RE.search(seg) or
                    re.search(r"алюмин|стал", low)):
                res.unparsed.append(seg)
            continue

        side = _side(seg)
        pts = _points(seg)
        depth = DEPTH_RE.search(seg)
        depth_v = _f(depth.group(1)) if depth else None
        through = bool(THROUGH_RE.search(seg))
        tol = TOL_RE.search(seg)
        ra = RA_RE.search(seg)
        cnt = max(_count(seg), len(pts) or 1)

        f = None
        if kind == "thread":
            m = THREAD_RE.search(seg)
            if not m:
                res.unparsed.append(seg)
                continue
            size_s = "M" + m.group(1).replace(",", ".") + (f"x{m.group(2).replace(',', '.')}" if m.group(2) else "")
            f = ThreadFeature(size=size_s, depth=depth_v, through=through, count=cnt, positions=pts, side=side)
        elif kind == "hole":
            cb = COUNTERBORE_RE.search(seg)
            rest = COUNTERBORE_RE.sub(" ", seg) if cb else seg
            dm = DIA_RE.search(rest)
            if not dm:
                res.unparsed.append(seg)
                continue
            fit = FIT_RE.search(rest[dm.start():dm.end() + 6])
            depth_h = DEPTH_RE.search(rest)
            f = HoleFeature(
                diameter=_f(dm.group(1)), depth=_f(depth_h.group(1)) if depth_h else None,
                through=through or not depth_h, count=cnt, positions=pts, side=side,
                fit=fit.group(1).replace("Н", "H").replace(" ", "") if fit else None,
                ra=_f(ra.group(1)) if ra else None,
                counterbore=Counterbore(diameter=_f(cb.group(1)), depth=_f(cb.group(2))) if cb else None,
            )
        elif kind in ("pocket", "slot"):
            m2 = SIZE2_RE.search(seg)
            if not m2:
                res.unparsed.append(seg)
                continue
            a, b = _f(m2.group(1)), _f(m2.group(2))
            d = _f(m2.group(3)) if m2.group(3) else depth_v
            if d is None and not through:
                res.missing.append(f"глубина: «{seg}»")
                d = 5.0
            r = RADIUS_RE.search(seg)
            common = dict(length=max(a, b), width=min(a, b), depth=d or 0.0, through=through, count=_count(seg),
                          center=pts[0] if pts else None, along="x" if a >= b else "y",
                          side=side, tolerance=_f(tol.group(1)) if tol else None, ra=_f(ra.group(1)) if ra else None)
            if kind == "pocket":
                f = PocketFeature(corner_radius=_f(r.group(1)) if r else 0.0,
                                  open_side=bool(re.search(r"открыт", low)),
                                  **common)
            else:
                f = SlotFeature(open_ends=bool(re.search(r"открыт|сквозн\w*\s+по\s+длин", low)), **common)
        elif kind == "chamfer":
            m = CHAMFER_RE.search(seg)
            sz = _f(m.group(1) or m.group(2)) if m else 0.5
            edges = "all" if re.search(r"все|всех|везде", low) else "holes" if "отв" in low else \
                "pockets" if re.search(r"карман|паз", low) else "outer"
            f = ChamferFeature(size=sz, edges=edges, side=side)
        elif kind == "face":
            f = FaceFeature(side=side, ra=_f(ra.group(1)) if ra else None)
        elif kind == "surface3d":
            r = RADIUS_RE.search(seg)
            f = SurfaceFeature(description=seg, depth=depth_v, side=side,
                               min_concave_radius=_f(r.group(1)) if r else None, ra=_f(ra.group(1)) if ra else None)
        elif kind == "contour":
            r = RADIUS_RE.search(seg)
            f = ContourFeature(tolerance=_f(tol.group(1)) if tol else None, ra=_f(ra.group(1)) if ra else None,
                               corner_radius=_f(r.group(1)) if r else 0.0)
        if f is not None:
            feats.append(f)
            if CORNERS_RE.search(seg) or CENTER_RE.search(seg):
                deferred_positions.append((f, seg))

    if size is None:
        res.missing.append("габарит детали (Д×Ш×В, мм)")
    if size is not None:
        for f, seg in deferred_positions:
            mc = CORNERS_RE.search(seg)
            if mc and isinstance(f, (HoleFeature, ThreadFeature)) and not f.positions:
                o = _f(mc.group(1)) if mc.group(1) else None
                if o is None:
                    res.missing.append(f"отступ от края для «{seg}» — принято 10 мм")
                    o = 10.0
                f.positions = [(o, o), (size.x - o, o), (o, size.y - o), (size.x - o, size.y - o)]
                f.count = 4
            elif CENTER_RE.search(seg):
                c = (size.x / 2, size.y / 2)
                if isinstance(f, (HoleFeature, ThreadFeature)) and not f.positions:
                    f.positions = [c]
                elif isinstance(f, (PocketFeature, SlotFeature)) and f.center is None:
                    f.center = c
        for f in feats:
            if isinstance(f, (HoleFeature, PocketFeature, SlotFeature)) and getattr(f, "through", False):
                if isinstance(f, HoleFeature) and f.depth is None:
                    f.depth = size.z if f.side in ("top", "bottom") else None

    res.features = feats
    res.material = mat_text
    material_name = None
    if mat_text:
        try:
            material_name = resolve_material(mat_text).name
        except UnknownMaterial as e:
            res.missing.append(str(e))
    if size is not None and material_name:
        res.part = Part(name=name or "Деталь", material=material_name, size=size, stock=stock, quantity=qty,
                        features=feats, general_tolerance=gentol)
    return res
