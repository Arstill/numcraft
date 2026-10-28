"""
Разбор STEP (ISO 10303-21, AP203/AP214/AP242) без OpenCascade.

Что извлекается:
- единицы, имя изделия, габарит (по вершинам B-rep);
- отверстия: вогнутые цилиндрические грани, сгруппированные по оси и радиусу (полные — отверстия,
  неполные — внутренние радиусы); сквозное/глухое — по соседним граням торцов; соосные ступени — цековки;
- полы карманов/уступов: горизонтальные плоские грани ниже верха, смотрящие вверх (или вниз — для низа);
- признаки 3D: B-сплайновые, торовые, сферические поверхности;
- направления обработки → число установов.

Результат — StepAnalysis и черновой Part (to_part). Резьбы по геометрии не видны: отверстия под метчик
(Ø5.0, Ø6.8…) помечаются вопросом.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from numcraft.knowledge.tooling import METRIC_COARSE
from numcraft.models import Box, Counterbore, HoleFeature, Part, PocketFeature, SurfaceFeature, _n

Vec = Tuple[float, float, float]


class Ref(int):
    pass


# ----------------------------------------------------------------------------- парсер Part 21

def _split_entities(data: str):
    out, buf, q = [], [], False
    for ch in data:
        if ch == "'":
            q = not q
        if ch == ";" and not q:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    return out


def _parse_args(s: str, i: int = 0):
    """Разбор списка аргументов, начиная после '('. Возвращает (list, index после ')')."""
    items, tok = [], ""
    while i < len(s):
        ch = s[i]
        if ch == "'":
            j = s.index("'", i + 1)
            while j + 1 < len(s) and s[j + 1] == "'":
                j = s.index("'", j + 2)
            items.append(s[i + 1:j])
            i = j + 1
            tok = None
            continue
        if ch == "(":
            sub, i = _parse_args(s, i + 1)
            if tok and tok.strip():  # типизированный параметр: LENGTH_MEASURE(1.0)
                items.append((tok.strip(), sub))
            else:
                items.append(sub)
            tok = None
            continue
        if ch in ",)":
            if tok is not None and tok.strip():
                items.append(_atom(tok.strip()))
            tok = ""
            i += 1
            if ch == ")":
                return items, i
            continue
        tok = (tok or "") + ch
        i += 1
    return items, i


def _atom(t: str):
    if t.startswith("#"):
        return Ref(int(t[1:]))
    if t.startswith("."):
        return t
    try:
        return float(t)
    except ValueError:
        return t


ENTITY_RE = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]*)\s*\((.*)\)\s*$", re.DOTALL)


def parse_step(text: str) -> Tuple[Dict[int, Tuple[str, list]], str]:
    m = re.search(r"\bDATA\s*;(.*?)ENDSEC\s*;", text, re.DOTALL)
    if not m:
        raise ValueError("Это не STEP-файл (нет секции DATA).")
    ents: Dict[int, Tuple[str, list]] = {}
    for raw in _split_entities(m.group(1)):
        em = ENTITY_RE.match(raw)
        if not em:
            continue
        eid, name, body = int(em.group(1)), em.group(2), em.group(3)
        if not name:  # комплексная сущность ( A() B() ) — храним как текст
            ents[eid] = ("COMPLEX", [body])
            continue
        try:
            args, _ = _parse_args(body + ")", 0)
        except ValueError:
            continue
        ents[eid] = (name, args)
    header = text[: m.start()]
    return ents, header


# ----------------------------------------------------------------------------- геометрия

def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(a: Vec) -> Vec:
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


AXES = {(1, 0, 0): "X", (0, 1, 0): "Y", (0, 0, 1): "Z"}


def _snap_axis(d: Vec) -> Optional[Tuple[str, int]]:
    for v, name in AXES.items():
        c = _dot(d, v)
        if abs(abs(c) - 1) < 1e-3:
            return name, (1 if c > 0 else -1)
    return None


@dataclass
class StepHole:
    diameter: float
    axis: str  # X/Y/Z или "наклонная"
    position: Vec  # точка на оси (в СК файла)
    t_min: float
    t_max: float
    through: bool
    open_end: int  # +1: открыт в сторону +axis, -1: в сторону −axis, 0: оба (сквозное)
    counterbore: Optional[Tuple[float, float]] = None  # (Ø, глубина)
    faces: int = 1

    @property
    def depth(self) -> float:
        return round(self.t_max - self.t_min, 3)


@dataclass
class StepFloor:
    z: float
    normal: int  # +1 вверх, -1 вниз
    bbox: Tuple[float, float, float, float]  # xmin, xmax, ymin, ymax
    open_side: bool


@dataclass
class StepAnalysis:
    file_name: str = ""
    product: str = ""
    schema: str = ""
    units: str = "мм"
    bbox_min: Vec = (0, 0, 0)
    bbox_max: Vec = (0, 0, 0)
    faces: int = 0
    surface_types: Dict[str, int] = field(default_factory=dict)
    holes: List[StepHole] = field(default_factory=list)
    inner_radii: List[float] = field(default_factory=list)
    floors: List[StepFloor] = field(default_factory=list)
    directions: List[str] = field(default_factory=list)
    is_3d: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def size(self) -> Vec:
        return tuple(round(self.bbox_max[i] - self.bbox_min[i], 3) for i in range(3))  # type: ignore


class _Model:
    def __init__(self, ents: Dict[int, Tuple[str, list]], scale: float):
        self.e = ents
        self.k = scale

    def name(self, r) -> str:
        return self.e.get(int(r), ("?", []))[0]

    def args(self, r) -> list:
        return self.e[int(r)][1]

    def point(self, r) -> Vec:
        c = self.args(r)[1]
        c = list(c) + [0.0] * (3 - len(c))
        return (c[0] * self.k, c[1] * self.k, c[2] * self.k)

    def direction(self, r) -> Vec:
        c = self.args(r)[1]
        c = list(c) + [0.0] * (3 - len(c))
        return _unit((c[0], c[1], c[2]))

    def placement(self, r) -> Tuple[Vec, Vec]:
        a = self.args(r)
        loc = self.point(a[1])
        axis = self.direction(a[2]) if isinstance(a[2], Ref) else (0.0, 0.0, 1.0)
        return loc, axis

    def face_loops(self, face) -> List[List[int]]:
        """Список контуров грани, каждый — список id EDGE_CURVE."""
        loops = []
        for b in self.args(face)[1]:
            bound = self.args(b)
            loop = bound[1]
            if self.name(loop) != "EDGE_LOOP":
                loops.append([])
                continue
            edges = []
            for oe in self.args(loop)[1]:
                ec = self.args(oe)[3]
                edges.append(int(ec))
            loops.append(edges)
        return loops

    def edge_vertices(self, ec) -> Tuple[Vec, Vec]:
        a = self.args(ec)
        return self.point(self.args(a[1])[1]), self.point(self.args(a[2])[1])

    def edge_closed(self, ec) -> bool:
        a = self.args(ec)
        return int(a[1]) == int(a[2])

    def edge_curve_type(self, ec) -> str:
        c = self.args(ec)[3]
        name = self.name(c)
        if name in ("SURFACE_CURVE", "SEAM_CURVE"):  # обёртка OCC/SolidWorks: 3D-кривая — 2-й аргумент
            name = self.name(self.args(c)[1])
        return name


def _units_scale(raw: str) -> Tuple[float, str]:
    if re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'INCH'", raw, re.IGNORECASE):
        return 25.4, "дюймы (пересчитано в мм)"
    if re.search(r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", raw):
        return 1.0, "мм"
    if re.search(r"SI_UNIT\s*\(\s*\.CENTI\.\s*,\s*\.METRE\.\s*\)", raw):
        return 10.0, "см (пересчитано в мм)"
    if re.search(r"SI_UNIT\s*\(\s*\$\s*,\s*\.METRE\.\s*\)", raw):
        return 1000.0, "м (пересчитано в мм)"
    return 1.0, "мм (не указаны — принято)"


def analyze_step(text: str, file_name: str = "") -> StepAnalysis:
    ents, header = parse_step(text)
    scale, units = _units_scale(text)
    md = _Model(ents, scale)
    res = StepAnalysis(file_name=file_name, units=units)
    if m := re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", header):
        res.schema = m.group(1)
    for eid, (name, args) in ents.items():
        if name == "PRODUCT" and args and isinstance(args[0], str):
            res.product = args[1] if len(args) > 1 and isinstance(args[1], str) and args[1] else args[0]
            break

    # габарит по вершинам
    pts = [md.point(args[1]) for name, args in ents.values() if name == "VERTEX_POINT"]
    if not pts:
        raise ValueError("В STEP нет B-rep вершин — нужна твердотельная модель (не сетка/поверхности).")
    res.bbox_min = tuple(min(p[i] for p in pts) for i in range(3))  # type: ignore
    res.bbox_max = tuple(max(p[i] for p in pts) for i in range(3))  # type: ignore

    # грани
    faces = [eid for eid, (n, _) in ents.items() if n in ("ADVANCED_FACE", "FACE_SURFACE")]
    res.faces = len(faces)
    surf_count: Dict[str, int] = defaultdict(int)
    for name, args in ents.values():
        if name == "COMPLEX" and "B_SPLINE_SURFACE" in args[0]:
            surf_count["B_SPLINE_SURFACE"] += 1
    edge_faces: Dict[int, List[Tuple[int, int]]] = defaultdict(list)  # edge → [(face, loop_index)]
    face_info: Dict[int, dict] = {}
    for f in faces:
        fa = md.args(f)
        surf = fa[2]
        sname = md.name(surf)
        if sname != "COMPLEX":
            surf_count[sname] += 1
        same = fa[3] == ".T."
        loops = md.face_loops(f)
        for li, lp in enumerate(loops):
            for ec in lp:
                edge_faces[ec].append((f, li))
        face_info[f] = {"surf": surf, "type": sname, "same": same, "loops": loops}
    res.surface_types = dict(surf_count)

    # --- цилиндры
    groups: Dict[tuple, List[dict]] = defaultdict(list)
    for f, fi in face_info.items():
        if fi["type"] != "CYLINDRICAL_SURFACE":
            continue
        sa = md.args(fi["surf"])
        loc, axis = md.placement(sa[1])
        r = round(sa[2] * scale, 4)
        if fi["same"]:
            continue  # выпуклая (бобышка, наружное скругление)
        # каноническая ось: направление со знаком «+» по наибольшей компоненте
        big = max(range(3), key=lambda i: abs(axis[i]))
        if axis[big] < 0:
            axis = (-axis[0], -axis[1], -axis[2])
        t = _dot(loc, axis)
        foot = tuple(round(loc[i] - t * axis[i], 2) for i in range(3))
        key = (tuple(round(a, 3) for a in axis), foot, r)
        verts = [p for lp in fi["loops"] for ec in lp for p in md.edge_vertices(ec)]
        ts = [_dot(_sub(p, foot), axis) for p in verts] or [0.0]
        closed = any(md.edge_closed(ec) and md.edge_curve_type(ec) in ("CIRCLE", "ELLIPSE")
                     for lp in fi["loops"] for ec in lp)
        groups[key].append({"face": f, "t": (min(ts), max(ts)), "closed": closed, "edges": [ec for lp in fi["loops"] for ec in lp]})

    by_axis_line: Dict[tuple, List[StepHole]] = defaultdict(list)
    for (axis, foot, r), items in groups.items():
        full = any(it["closed"] for it in items) or len(items) >= 2
        if not full:
            res.inner_radii.append(r)
            continue
        t_min = min(it["t"][0] for it in items)
        t_max = max(it["t"][1] for it in items)
        hole_faces = {it["face"] for it in items}
        hole_edges = {ec for it in items for ec in it["edges"]}

        def end_open(t_end: float) -> bool:
            for it in items:
                for ec in it["edges"]:
                    if md.edge_curve_type(ec) != "CIRCLE":
                        continue
                    p1, p2 = md.edge_vertices(ec)
                    if abs(_dot(_sub(p1, foot), axis) - t_end) > 1e-3:
                        continue
                    for nf, li in edge_faces.get(ec, []):
                        if nf in hole_faces:
                            continue
                        nfi = face_info[nf]
                        if nfi["type"] != "PLANE":
                            return False  # конус сверла, сфера
                        if len(nfi["loops"]) == 1:
                            return False  # дно-«диск»
                        return all(e in hole_edges for e in nfi["loops"][li])
            return False

        o_lo, o_hi = end_open(t_min), end_open(t_max)
        axis_s = _snap_axis(axis)
        hole = StepHole(
            diameter=round(2 * r, 3), axis=axis_s[0] if axis_s else "наклонная",
            position=tuple(foot[i] + 0 for i in range(3)), t_min=t_min, t_max=t_max,  # type: ignore
            through=o_lo and o_hi, open_end=0 if (o_lo and o_hi) else (1 if o_hi else -1 if o_lo else 0),
            faces=len(items),
        )
        by_axis_line[(axis, foot)].append(hole)

    # соосные ступени → цековки
    for (axis, foot), hs in by_axis_line.items():
        hs.sort(key=lambda h: h.diameter)
        base = hs[0]
        for big in hs[1:]:
            if base.counterbore is None and (big.t_max >= base.t_max - 1e-3 or big.t_min <= base.t_min + 1e-3):
                base.counterbore = (big.diameter, big.depth)
                if big.t_max >= base.t_max - 1e-3:
                    base.t_max = big.t_max
                    base.open_end = base.open_end or 1
                else:
                    base.t_min = big.t_min
            else:
                res.holes.append(big)
        res.holes.append(base)

    # --- полы карманов/уступов
    zmin, zmax = res.bbox_min[2], res.bbox_max[2]
    for f, fi in face_info.items():
        if fi["type"] != "PLANE":
            continue
        loc, axis = md.placement(md.args(fi["surf"])[1])
        n = axis if fi["same"] else (-axis[0], -axis[1], -axis[2])
        snap = _snap_axis(n)
        if not snap or snap[0] != "Z":
            continue  # боковые стенки обрабатываются сверху контуром
        z = loc[2]
        if abs(z - zmax) < 1e-3 or abs(z - zmin) < 1e-3:
            continue
        outer = fi["loops"][0] if fi["loops"] else []
        if all(md.edge_curve_type(ec) in ("CIRCLE", "ELLIPSE") for ec in outer) and len(fi["loops"]) == 1:
            continue  # дно глухого отверстия
        vs = [p for ec in outer for p in md.edge_vertices(ec)]
        if not vs:
            continue
        bb = (min(p[0] for p in vs), max(p[0] for p in vs), min(p[1] for p in vs), max(p[1] for p in vs))
        tol = 0.01
        open_side = (bb[0] - res.bbox_min[0] < tol or res.bbox_max[0] - bb[1] < tol or
                     bb[2] - res.bbox_min[1] < tol or res.bbox_max[1] - bb[3] < tol)
        res.floors.append(StepFloor(z=round(z, 3), normal=snap[1], bbox=bb, open_side=open_side))
        res.directions.append("+Z" if snap[1] > 0 else "-Z")

    for h in res.holes:
        if h.axis == "Z":
            res.directions.append("-Z" if h.open_end == -1 else "+Z")
        elif h.axis in ("X", "Y"):
            res.directions.append(("+" if h.open_end >= 0 else "-") + h.axis)
        else:
            res.warnings.append(f"Наклонное отверстие Ø{_n(h.diameter)} — для 3-осевой обработки нужна оснастка/поворот.")
    res.directions = sorted(set(res.directions))
    free_form = sum(v for k, v in surf_count.items() if k in ("B_SPLINE_SURFACE_WITH_KNOTS", "B_SPLINE_SURFACE",
                                                              "SPHERICAL_SURFACE", "SURFACE_OF_REVOLUTION",
                                                              "SURFACE_OF_LINEAR_EXTRUSION"))
    torus = surf_count.get("TOROIDAL_SURFACE", 0)
    res.is_3d = free_form > 0 or torus > 8
    if torus and not res.is_3d:
        res.warnings.append(f"Торовые грани ({torus}) — вероятно, скругления дна кармана: нужна радиусная фреза.")
    res.inner_radii = sorted(set(res.inner_radii))
    return res


def analyze_step_file(path: str) -> StepAnalysis:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    return analyze_step(text, file_name=path)


# ----------------------------------------------------------------------------- → Part

TAP_DRILLS = {drill: f"M{_n(size)}" for size, (_, drill) in METRIC_COARSE.items()}


def to_part(a: StepAnalysis, material: str, name: Optional[str] = None) -> Tuple[Part, List[str]]:
    """Черновой Part: X0 Y0 — левый передний угол, Z0 — верх модели."""
    sx, sy, sz = a.size
    x0, y0, z_top = a.bbox_min[0], a.bbox_min[1], a.bbox_max[2]
    notes: List[str] = []
    feats = []
    holes_z: Dict[tuple, List[Tuple[float, float]]] = defaultdict(list)
    for h in a.holes:
        if h.axis != "Z":
            notes.append(f"Отверстие Ø{_n(h.diameter)} по оси {h.axis} — боковой установ, добавьте вручную "
                         f"(side=front/back/left/right).")
            continue
        side = "bottom" if h.open_end == -1 else "top"
        # Z входа: верх отверстия относительно верха модели (для отверстий в дне кармана < 0)
        z_start = round(h.t_max - z_top, 3) if side == "top" else round(a.bbox_min[2] - h.t_min, 3)
        cb = (round(h.counterbore[0], 3), round(h.counterbore[1], 3)) if h.counterbore else None
        key = (h.diameter, round(h.depth, 3), h.through, side, cb, z_start)
        holes_z[key].append((round(h.position[0] - x0, 3), round(h.position[1] - y0, 3)))
    for (d, depth, through, side, cb, z_start), pts in holes_z.items():
        feats.append(HoleFeature(diameter=d, depth=depth, through=through, count=len(pts), positions=pts, side=side,
                                 z_start=z_start, counterbore=Counterbore(diameter=cb[0], depth=cb[1]) if cb else None))
        for drill, thread in TAP_DRILLS.items():
            if abs(d - drill) < 0.01:
                notes.append(f"Ø{_n(d)} ({len(pts)} шт.) — диаметр под метчик {thread}: если это резьба, "
                             f"замените на thread {thread}.")
    r_min = min(a.inner_radii) if a.inner_radii else 0.0
    for fl in a.floors:
        if fl.normal < 0:
            notes.append(f"Обращённая вниз плоскость на Z{_n(fl.z - z_top)} — элемент с обратной стороны.")
            continue
        L, W = round(fl.bbox[1] - fl.bbox[0], 3), round(fl.bbox[3] - fl.bbox[2], 3)
        cx, cy = (fl.bbox[0] + fl.bbox[1]) / 2 - x0, (fl.bbox[2] + fl.bbox[3]) / 2 - y0
        depth = round(z_top - fl.z, 3)
        feats.append(PocketFeature(length=max(L, W), width=min(L, W), depth=depth, corner_radius=r_min,
                                   open_side=fl.open_side, center=(round(cx, 3), round(cy, 3)),
                                   along="x" if L >= W else "y", note="из STEP: пол на Z" + _n(-depth)))
    if a.is_3d:
        feats.append(SurfaceFeature(description="поверхности свободной формы из STEP",
                                    min_concave_radius=r_min or None))
    if a.inner_radii:
        notes.append("Внутренние радиусы в модели: " + ", ".join(f"R{_n(r)}" for r in a.inner_radii) +
                     " — финишная фреза меньше 2×Rmin.")
    part = Part(name=name or a.product or "Деталь из STEP", material=material, size=Box(x=sx, y=sy, z=sz),
                features=feats)
    return part, notes + a.warnings


def summary_ru(a: StepAnalysis) -> str:
    sx, sy, sz = a.size
    lines = [
        f"STEP: {a.file_name or '—'}  ({a.schema or 'схема не указана'})",
        f"Изделие: {a.product or '—'}; единицы: {a.units}",
        f"Габарит: {_n(sx)} × {_n(sy)} × {_n(sz)} мм; граней: {a.faces}",
        "Поверхности: " + ", ".join(f"{k}={v}" for k, v in sorted(a.surface_types.items())),
        f"Тип обработки: {'3D (есть поверхности свободной формы)' if a.is_3d else '2.5D'}",
        f"Направления обработки: {', '.join(a.directions) or '+Z'}",
    ]
    if a.holes:
        lines.append(f"Отверстия ({len(a.holes)}):")
        for h in sorted(a.holes, key=lambda h: (h.axis, h.diameter)):
            cb = f", цековка Ø{_n(h.counterbore[0])}×{_n(h.counterbore[1])}" if h.counterbore else ""
            kind = "сквозное" if h.through else "глухое"
            lines.append(f"  Ø{_n(h.diameter)} ось {h.axis}, {kind}, длина {_n(h.depth)} мм, "
                         f"точка ({_n(h.position[0])}; {_n(h.position[1])}; {_n(h.position[2])}){cb}")
    if a.floors:
        lines.append("Полы карманов/уступов:")
        for fl in a.floors:
            lines.append(f"  Z={_n(fl.z)} ({'вверх' if fl.normal > 0 else 'вниз'}), "
                         f"{_n(fl.bbox[1] - fl.bbox[0])}×{_n(fl.bbox[3] - fl.bbox[2])}"
                         f"{', открыт к краю' if fl.open_side else ''}")
    if a.inner_radii:
        lines.append("Внутренние радиусы: " + ", ".join(f"R{_n(r)}" for r in a.inner_radii))
    lines += [f"! {w}" for w in a.warnings]
    return "\n".join(lines)
