"""
Схемы для техкарты: вид сверху детали в системе координат установа (SVG).

Для каждой операции подсвечивается то, что она обрабатывает: заготовка (торцовка), зона между
заготовкой и контуром (черновая контура), кромка контура, карман/дно/стенки, отверстия
(с порядком обхода), кромки под фаску. Размеры — в мм, ось Y вверх, как на станке.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from numcraft.models import (
    ContourFeature, HoleFeature, Operation, PocketFeature, Setup, SlotFeature, TechSheet, ThreadFeature, _n,
)

AREA = {"pocket_area", "pocket_corners", "pocket_floor", "slot_area"}
WALLS = {"pocket_walls", "slot_walls"}
HOLES = {"holes", "hole_walls", "hole_area", "thread"}

GEOM_RU = {
    "face": "верхняя плоскость заготовки",
    "outer_rough": "припуск вокруг наружного контура",
    "outer_walls": "наружный контур (кромка)",
    "pocket_area": "объём кармана",
    "pocket_corners": "остаток в углах кармана",
    "pocket_floor": "дно кармана",
    "pocket_walls": "стенки кармана",
    "slot_area": "паз",
    "slot_walls": "стенки паза",
    "holes": "отверстия (цифры — порядок обхода)",
    "hole_area": "выборка отверстия",
    "hole_walls": "стенка отверстия",
    "thread": "резьбовые отверстия",
    "chamfer_outer": "верхняя кромка контура",
    "chamfer_pockets": "кромки карманов и пазов",
    "chamfer_holes": "кромки отверстий",
    "chamfer_all": "все верхние кромки",
    "surface": "3D-поверхность (зона по модели)",
}


class _Frame:
    """Координаты детали (X0 Y0 — левый передний угол, вид сверху) → СК установа → SVG."""

    def __init__(self, sheet: TechSheet, setup: Setup):
        from numcraft.faces import face_dims
        from numcraft.models import Box

        self.side = setup.side
        self.center = sheet.part.datum == "center"
        w, h, _ = face_dims(setup.side, sheet.part.size)
        self.p = Box(x=w, y=h, z=0)  # размеры грани в виде на неё
        top_bottom = setup.side in ("top", "bottom")
        mx = (sheet.stock.x - sheet.part.size.x) / 2 if top_bottom else 0.0
        my = (sheet.stock.y - sheet.part.size.y) / 2 if top_bottom else 0.0
        x0, y0 = self.to_setup(-mx, -my)
        x1, y1 = self.to_setup(self.p.x + mx, self.p.y + my)
        self.xmin, self.xmax = min(x0, x1), max(x0, x1)
        self.ymin, self.ymax = min(y0, y1), max(y0, y1)
        size = max(self.xmax - self.xmin, self.ymax - self.ymin)
        self.pad = size * 0.12
        self.fs = size * 0.035  # размер шрифта, мм
        self.dash = f"{_n(round(size / 70, 2))} {_n(round(size / 110, 2))}"

    def to_setup(self, x: float, y: float) -> Tuple[float, float]:
        if self.side == "bottom":
            y = self.p.y - y
        if self.center:
            x, y = x - self.p.x / 2, y - self.p.y / 2
        return x, y

    def svg(self, x: float, y: float) -> Tuple[float, float]:
        """Точка уже в СК установа → координаты SVG."""
        return round(x - self.xmin + self.pad, 3), round(self.ymax - y + self.pad, 3)

    def part_pt(self, x: float, y: float) -> Tuple[float, float]:
        return self.svg(*self.to_setup(x, y))

    @property
    def width(self) -> float:
        return self.xmax - self.xmin + 2 * self.pad

    @property
    def height(self) -> float:
        return self.ymax - self.ymin + 2 * self.pad


def _rect(fr: _Frame, x0, y0, x1, y1, cls: str, r: float = 0.0, from_part: bool = True, dashed: bool = False) -> str:
    a = fr.part_pt(x0, y0) if from_part else fr.svg(x0, y0)
    b = fr.part_pt(x1, y1) if from_part else fr.svg(x1, y1)
    x, y = min(a[0], b[0]), min(a[1], b[1])
    w, h = abs(a[0] - b[0]), abs(a[1] - b[1])
    rx = f' rx="{_n(r)}"' if r else ""
    da = f' stroke-dasharray="{fr.dash}"' if dashed else ""
    return f'<rect class="{cls}" x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"{rx}{da}/>'


def _feature_box(f) -> Optional[Tuple[float, float, float, float]]:
    if not isinstance(f, (PocketFeature, SlotFeature)) or f.center is None:
        return None
    cx, cy = f.center
    lx, ly = (f.length, f.width) if f.along == "x" else (f.width, f.length)
    return cx - lx / 2, cy - ly / 2, cx + lx / 2, cy + ly / 2


def _visible(f, side: str) -> Optional[str]:
    """'own' — элемент этого установа, 'ref' — виден насквозь (пунктир), None — не рисуем."""
    if f.side == side:
        return "own"
    if side in ("top", "bottom") and f.side in ("top", "bottom") and getattr(f, "through", False):
        return "ref"
    return None


def setup_svg(sheet: TechSheet, setup: Setup, op: Optional[Operation] = None) -> str:
    fr = _Frame(sheet, setup)
    geom = op.geom if op else ""
    ids = set(op.feature_ids) if op else set()
    ps = fr.p  # грань установа: ширина × высота
    contour = next((f for f in sheet.part.features if isinstance(f, ContourFeature)), None)
    cr = contour.corner_radius if contour and setup.side in ("top", "bottom") else 0.0
    el: List[str] = []
    unplaced: List[str] = []

    # заготовка и деталь
    el.append(_rect(fr, fr.xmin, fr.ymin, fr.xmax, fr.ymax, "hl" if geom == "face" else "stock",
                    from_part=False, dashed=geom != "face"))
    if geom == "outer_rough":
        a, b = fr.svg(fr.xmin, fr.ymax), fr.svg(fr.xmax, fr.ymin)
        p0, p1 = fr.part_pt(0, 0), fr.part_pt(ps.x, ps.y)
        x0, x1 = sorted((p0[0], p1[0]))
        y0, y1 = sorted((p0[1], p1[1]))
        el.append(f'<path class="hl" fill-rule="evenodd" d="M{_n(a[0])} {_n(a[1])}H{_n(b[0])}V{_n(b[1])}'
                  f'H{_n(a[0])}Z M{_n(x0)} {_n(y0)}H{_n(x1)}V{_n(y1)}H{_n(x0)}Z"/>')
    el.append(_rect(fr, 0, 0, ps.x, ps.y, "part", r=cr))
    if geom in ("outer_walls", "outer_rough"):
        el.append(_rect(fr, 0, 0, ps.x, ps.y, "hll", r=cr))
    if geom in ("chamfer_outer", "chamfer_all"):
        el.append(_rect(fr, 0, 0, ps.x, ps.y, "hll", r=cr, dashed=True))

    labels: List[str] = []
    for f in sheet.part.features:
        vis = _visible(f, setup.side)
        if vis is None:
            continue
        mine = f.id in ids and vis == "own"
        if isinstance(f, (PocketFeature, SlotFeature)):
            box = _feature_box(f)
            if box is None:
                if vis == "own":
                    kind = "карман" if isinstance(f, PocketFeature) else "паз"
                    unplaced.append(f"{f.id} ({kind} {_n(f.length)}×{_n(f.width)})")
                continue
            r = f.corner_radius if isinstance(f, PocketFeature) else min(f.length, f.width) / 2
            if vis == "ref":
                el.append(_rect(fr, *box, "ref", r=r, dashed=True))
                continue
            hl_area = mine and geom in AREA
            el.append(_rect(fr, *box, "hl" if hl_area else "feat", r=r))
            if (mine and geom in WALLS) or geom in ("chamfer_pockets", "chamfer_all"):
                el.append(_rect(fr, *box, "hll", r=r, dashed=geom.startswith("chamfer")))
            lx, ly = fr.part_pt(box[2], box[3])
            labels.append(f'<text x="{_n(lx)}" y="{_n(ly - fr.fs * 0.3)}" text-anchor="end">{f.id}</text>')
        elif isinstance(f, (HoleFeature, ThreadFeature)):
            if not f.positions:
                if vis == "own":
                    unplaced.append(f"{f.id} ({'Ø' + _n(f.diameter) if isinstance(f, HoleFeature) else f.size})")
                continue
            if isinstance(f, HoleFeature):
                rr = f.diameter / 2
                outer = f.counterbore.diameter / 2 if f.counterbore else None
            else:
                from numcraft.knowledge.tooling import parse_thread, tap_drill
                d, pitch = parse_thread(f.size)
                rr, outer = tap_drill(d, pitch) / 2, d / 2
            for x, y in f.positions:
                cx, cy = fr.part_pt(x, y)
                if vis == "ref":
                    el.append(f'<circle class="ref" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(rr)}" '
                              f'stroke-dasharray="{fr.dash}"/>')
                    continue
                cls = "hl" if mine and geom in HOLES else "feat"
                if outer:
                    dash = f' stroke-dasharray="{fr.dash}"' if isinstance(f, ThreadFeature) else ""
                    el.append(f'<circle class="{"hll" if mine and geom in HOLES else "feat"}" cx="{_n(cx)}" '
                              f'cy="{_n(cy)}" r="{_n(outer)}" fill="none"{dash}/>')
                el.append(f'<circle class="{cls}" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(rr)}"/>')
                if geom in ("chamfer_holes", "chamfer_all"):
                    el.append(f'<circle class="hll" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(outer or rr)}" '
                              f'stroke-dasharray="{fr.dash}"/>')
            x, y = f.positions[0]
            lx, ly = fr.part_pt(x, y)
            labels.append(f'<text x="{_n(lx + (outer or rr) + fr.fs * 0.3)}" y="{_n(ly - (outer or rr))}">{f.id}</text>')

    # порядок обхода отверстий
    if op and geom in HOLES and op.positions:
        for i, (x, y) in enumerate(op.positions, 1):
            sx, sy = fr.svg(x, y)
            labels.append(f'<text class="num" x="{_n(sx)}" y="{_n(sy + fr.fs * 1.4)}" text-anchor="middle">{i}</text>')

    # нуль установа
    ox, oy = fr.svg(0, 0)
    L = fr.fs * 2.2
    el.append(f'<path class="datum" d="M{_n(ox)} {_n(oy)}h{_n(L)}M{_n(ox)} {_n(oy)}v{_n(-L)}" fill="none"/>')
    labels.append(f'<text class="datum-t" x="{_n(ox + L + fr.fs * 0.2)}" y="{_n(oy + fr.fs * 0.35)}">X</text>')
    labels.append(f'<text class="datum-t" x="{_n(ox - fr.fs * 0.3)}" y="{_n(oy - L - fr.fs * 0.2)}">Y</text>')
    labels.append(f'<text class="datum-t" x="{_n(ox - fr.fs * 0.4)}" y="{_n(oy + fr.fs * 1.3)}" '
                  f'text-anchor="end">{setup.wcs}</text>')
    # габарит
    bx, by = fr.part_pt(ps.x / 2, 0)
    if setup.side == "bottom":
        by = fr.part_pt(ps.x / 2, ps.y)[1]
    labels.append(f'<text x="{_n(bx)}" y="{_n(max(by, fr.svg(0, fr.ymin)[1]) + fr.fs * 1.6)}" '
                  f'text-anchor="middle">{_n(ps.x)}</text>')

    svg = (f'<svg class="sk" viewBox="0 0 {_n(round(fr.width, 2))} {_n(round(fr.height, 2))}" '
           f'style="font-size:{_n(round(fr.fs, 2))}px;--sw:{_n(round(fr.fs / 9, 3))}px" role="img" '
           f'aria-label="{setup.title}">' + "".join(el) + "".join(labels) + "</svg>")
    view = "Вид сверху" if setup.side in ("top", "bottom") else f"Вид на грань «{setup.title.split(' — ')[-1]}»"
    cap = [f"{view}, {setup.title.split(' — ')[0].lower()}, нуль {setup.wcs}."]
    if setup.side == "bottom":
        cap.append("Деталь перевёрнута вокруг X: пунктир — сквозные элементы с верхней стороны.")
    if op and geom:
        cap.append(f"Подсвечено: {GEOM_RU.get(geom, geom)}.")
    if unplaced:
        cap.append("Без координат (не показаны): " + ", ".join(unplaced) + ".")
    if op and geom == "surface":
        cap.append("Зону 3D-обработки задайте по модели в HSMWorks.")
    return f'<figure class="skf">{svg}<figcaption>{" ".join(cap)}</figcaption></figure>'
