"""
Данные для 3D-вида техкарты: рёбра детали (полилинии) с метками элементов.

Источник — рёбра STEP (если модель есть) или каркас, построенный по Part (габарит, карманы, пазы,
отверстия). Координаты — СК детали: X0 Y0 — левый передний угол, Z0 — верх, деталь ниже нуля.
Метки: id признака (F1…), "outer" — наружный контур, "top"/"bot" — рёбра верхней/нижней плоскости.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from numcraft.models import HoleFeature, PocketFeature, SlotFeature, TechSheet, ThreadFeature, ContourFeature
from numcraft.sketch import _feature_box

Vec = Tuple[float, float, float]
EPS = 0.02


def _circle(cx: float, cy: float, r: float, z: float, n: int = 48) -> List[Vec]:
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n + 1)]


def _rrect(x0, y0, x1, y1, r: float, z: float) -> List[Vec]:
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r <= 1e-6:
        return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), (x0, y0, z)]
    pts: List[Vec] = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for i in range(9):
            a = math.radians(a0 + 90 * i / 8)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    pts.append(pts[0])
    return pts


def _corners(x0, y0, x1, y1, r: float) -> List[Tuple[float, float]]:
    """Точки вертикальных рёбер (концы скруглений)."""
    if r <= 1e-6:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [(x0 + r, y0), (x1 - r, y0), (x1, y0 + r), (x1, y1 - r), (x1 - r, y1), (x0 + r, y1), (x0, y1 - r), (x0, y0 + r)]


def _synthetic(sheet: TechSheet) -> List[dict]:
    ps = sheet.part.size
    X, Y, Z = ps.x, ps.y, ps.z
    contour = next((f for f in sheet.part.features if isinstance(f, ContourFeature)), None)
    cr = contour.corner_radius if contour else 0.0
    edges = [
        {"p": _rrect(0, 0, X, Y, cr, 0), "t": ["outer", "top"]},
        {"p": _rrect(0, 0, X, Y, cr, -Z), "t": ["outer", "bot"]},
    ]
    edges += [{"p": [(x, y, 0), (x, y, -Z)], "t": ["outer"]} for x, y in _corners(0, 0, X, Y, cr)]
    for f in sheet.part.features:
        bottom = f.side == "bottom"
        if f.side not in ("top", "bottom"):
            continue

        def zz(depth_from_face: float) -> float:
            return -Z + depth_from_face if bottom else -depth_from_face

        if isinstance(f, (PocketFeature, SlotFeature)):
            box = _feature_box(f)
            if box is None:
                continue
            r = f.corner_radius if isinstance(f, PocketFeature) else min(f.length, f.width) / 2
            depth = Z if f.through else f.depth
            top, floor = zz(0), zz(depth)
            edges.append({"p": _rrect(*box, r, top), "t": [f.id, "bot" if bottom else "top"]})
            edges.append({"p": _rrect(*box, r, floor), "t": [f.id]})
            edges += [{"p": [(x, y, top), (x, y, floor)], "t": [f.id]} for x, y in _corners(*box, r)]
        elif isinstance(f, (HoleFeature, ThreadFeature)):
            if isinstance(f, HoleFeature):
                r = f.diameter / 2
                cb = f.counterbore
            else:
                from numcraft.knowledge.tooling import parse_thread, tap_drill
                d, p = parse_thread(f.size)
                r, cb = tap_drill(d, p) / 2, None
            depth = f.depth or (Z if f.through else 2 * r * 2)
            z0 = (-Z - f.z_start) if bottom else f.z_start
            z_end = z0 + depth if bottom else z0 - depth
            if f.through:
                z_end = 0.0 if bottom else -Z
            for x, y in f.positions:
                tags = [f.id]
                if cb:
                    zc = z0 + cb.depth if bottom else z0 - cb.depth
                    edges.append({"p": _circle(x, y, cb.diameter / 2, z0), "t": tags + ["bot" if bottom else "top"]})
                    edges.append({"p": _circle(x, y, cb.diameter / 2, zc), "t": tags})
                    edges.append({"p": _circle(x, y, r, zc), "t": tags})
                else:
                    edges.append({"p": _circle(x, y, r, z0), "t": tags + (["bot" if bottom else "top"] if not f.z_start else [])})
                edges.append({"p": _circle(x, y, r, z_end), "t": tags})
                if isinstance(f, ThreadFeature):
                    edges.append({"p": _circle(x, y, parse_thread(f.size)[0] / 2, z0), "t": tags})
    return edges


def _tag_step_edges(sheet: TechSheet, raw: Sequence[Sequence[Vec]], origin: Vec) -> List[dict]:
    ps = sheet.part.size
    X, Y, Z = ps.x, ps.y, ps.z
    holes = []
    for f in sheet.part.features:
        if isinstance(f, (HoleFeature, ThreadFeature)) and f.side in ("top", "bottom"):
            if isinstance(f, HoleFeature):
                r = max(f.diameter, f.counterbore.diameter if f.counterbore else 0) / 2
            else:
                from numcraft.knowledge.tooling import parse_thread
                r = parse_thread(f.size)[0] / 2
            holes += [(f.id, x, y, r) for x, y in f.positions]
    pockets = [(f.id, _feature_box(f), f) for f in sheet.part.features if isinstance(f, (PocketFeature, SlotFeature))]
    out = []
    for pl in raw:
        pts = [(round(p[0] - origin[0], 3), round(p[1] - origin[1], 3), round(p[2] - origin[2], 3)) for p in pl]
        tags: List[str] = []
        if all(abs(p[2]) < EPS for p in pts):
            tags.append("top")
        if all(abs(p[2] + Z) < EPS for p in pts):
            tags.append("bot")
        if all(abs(p[0]) < EPS for p in pts) or all(abs(p[0] - X) < EPS for p in pts) or \
                all(abs(p[1]) < EPS for p in pts) or all(abs(p[1] - Y) < EPS for p in pts):
            tags.append("outer")
        hole = next((hid for hid, hx, hy, hr in holes
                     if all(math.hypot(p[0] - hx, p[1] - hy) <= hr + 0.05 for p in pts)), None)
        if hole:
            tags.append(hole)
        else:
            for pid, box, f in pockets:
                if box is None:
                    continue
                depth = Z if f.through else f.depth
                if all(box[0] - 0.05 <= p[0] <= box[2] + 0.05 and box[1] - 0.05 <= p[1] <= box[3] + 0.05
                       and -depth - 0.05 <= p[2] <= 0.05 for p in pts):
                    tags.append(pid)
                    break
        out.append({"p": pts, "t": tags})
    return out


def build(sheet: TechSheet, step_edges: Optional[Sequence[Sequence[Vec]]] = None,
          step_origin: Optional[Vec] = None) -> dict:
    ps = sheet.part.size
    if step_edges:
        edges = _tag_step_edges(sheet, step_edges, step_origin or (0, 0, 0))
        source = "step"
    else:
        edges = _synthetic(sheet)
        source = "model"
    for e in edges:
        e["p"] = [[round(c, 2) for c in p] for p in e["p"]]
    top = next((s.stock_top for s in sheet.setups if s.side == "top"), 0.0)
    bot = next((s.stock_top for s in sheet.setups if s.side == "bottom"), 0.0)
    mx, my = (sheet.stock.x - ps.x) / 2, (sheet.stock.y - ps.y) / 2
    ops = [{"n": op.number, "title": op.title, "geom": op.geom, "ids": op.feature_ids, "side": s.side,
            "setup": s.title, "wcs": s.wcs}
           for s in sheet.setups for op in s.operations]
    return {
        "source": source,
        "size": [ps.x, ps.y, ps.z],
        "datum": sheet.part.datum,
        "stock": [-mx, -my, -ps.z - bot, ps.x + mx, ps.y + my, top],
        "edges": edges,
        "ops": ops,
        "pockets": [f.id for f in sheet.part.features if isinstance(f, (PocketFeature, SlotFeature))],
        "holes": [f.id for f in sheet.part.features if isinstance(f, (HoleFeature, ThreadFeature))],
    }
