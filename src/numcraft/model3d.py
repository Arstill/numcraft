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
from numcraft.faces import face_dims, from_face, to_face
from numcraft.sketch import _feature_box

FACE_SIDES = ("top", "bottom", "front", "back", "left", "right")

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
        if f.side not in ("top", "bottom", "front", "back", "left", "right"):
            continue
        face_tag = {"top": ["top"], "bottom": ["bot"]}.get(f.side, [])

        def m(pts: List[Vec]) -> List[Vec]:
            # (u, v, d) в СК грани → координаты детали
            return [from_face(f.side, u, v, d, ps) for u, v, d in pts]

        thick = face_dims(f.side, ps)[2]
        if isinstance(f, (PocketFeature, SlotFeature)):
            box = _feature_box(f)
            if box is None:
                continue
            r = f.corner_radius if isinstance(f, PocketFeature) else min(f.length, f.width) / 2
            depth = thick if f.through else f.depth
            edges.append({"p": m(_rrect(*box, r, 0)), "t": [f.id] + face_tag})
            edges.append({"p": m(_rrect(*box, r, depth)), "t": [f.id]})
            edges += [{"p": m([(u, v, 0), (u, v, depth)]), "t": [f.id]} for u, v in _corners(*box, r)]
        elif isinstance(f, (HoleFeature, ThreadFeature)):
            if isinstance(f, HoleFeature):
                r = f.diameter / 2
                cb = f.counterbore
            else:
                from numcraft.knowledge.tooling import parse_thread, tap_drill
                d, p = parse_thread(f.size)
                r, cb = tap_drill(d, p) / 2, None
            d0 = -f.z_start
            d_end = thick if f.through else d0 + (f.depth or 4 * r)
            for u, v in f.positions:
                tags = [f.id]
                if cb:
                    edges.append({"p": m(_circle(u, v, cb.diameter / 2, d0)), "t": tags + face_tag})
                    edges.append({"p": m(_circle(u, v, cb.diameter / 2, d0 + cb.depth)), "t": tags})
                    edges.append({"p": m(_circle(u, v, r, d0 + cb.depth)), "t": tags})
                else:
                    edges.append({"p": m(_circle(u, v, r, d0)), "t": tags + (face_tag if not f.z_start else [])})
                edges.append({"p": m(_circle(u, v, r, d_end)), "t": tags})
                if isinstance(f, ThreadFeature):
                    edges.append({"p": m(_circle(u, v, parse_thread(f.size)[0] / 2, d0)), "t": tags})
    return edges


def _tag_step_edges(sheet: TechSheet, raw: Sequence[Sequence[Vec]], origin: Vec) -> List[dict]:
    ps = sheet.part.size
    X, Y, Z = ps.x, ps.y, ps.z
    holes = []
    for f in sheet.part.features:
        if isinstance(f, (HoleFeature, ThreadFeature)) and f.side in FACE_SIDES:
            if isinstance(f, HoleFeature):
                r = max(f.diameter, f.counterbore.diameter if f.counterbore else 0) / 2
            else:
                from numcraft.knowledge.tooling import parse_thread
                r = parse_thread(f.size)[0] / 2
            d_end = face_dims(f.side, ps)[2] if f.through else -f.z_start + (f.depth or 4 * r)
            holes += [(f.id, f.side, u, v, r, -f.z_start, d_end) for u, v in f.positions]
    pockets = [(f.id, _feature_box(f), f) for f in sheet.part.features if isinstance(f, (PocketFeature, SlotFeature))
               and f.side in FACE_SIDES]
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
        hole = None
        for hid, side, hu, hv, hr, d0, d1 in holes:
            loc = [to_face(side, *p, ps) for p in pts]
            if all(math.hypot(q[0] - hu, q[1] - hv) <= hr + 0.05 and d0 - 0.05 <= q[2] <= d1 + 0.05 for q in loc):
                hole = hid
                break
        if hole:
            tags.append(hole)
        else:
            for pid, box, f in pockets:
                if box is None:
                    continue
                depth = face_dims(f.side, ps)[2] if f.through else f.depth
                loc = [to_face(f.side, *p, ps) for p in pts]
                if all(box[0] - 0.05 <= q[0] <= box[2] + 0.05 and box[1] - 0.05 <= q[1] <= box[3] + 0.05
                       and -0.05 <= q[2] <= depth + 0.05 for q in loc):
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
    def origin(s) -> list:
        # нуль установа в СК установа (грань вверх): центр/угол грани; Z0 установа 1 — верх заготовки
        w_, h_, _ = face_dims(s.side, ps)
        cx, cy = (w_ / 2, h_ / 2) if sheet.part.datum == "center" else (0.0, 0.0)
        return [round(cx, 2), round(cy, 2), round(s.z_shift, 2)]

    ops = [{"n": op.number, "title": op.title, "tool": f"T{op.tool.number} — {op.tool.label()}",
            "origin": origin(s), "geom": op.geom, "ids": op.feature_ids, "side": s.side,
            "setup": s.title, "wcs": s.wcs}
           for s in sheet.setups for op in s.operations]
    return {
        "source": source,
        "size": [ps.x, ps.y, ps.z],
        "datum": sheet.part.datum,
        "stock": [-mx, -my, -ps.z - bot, ps.x + mx, ps.y + my, top],
        "edges": edges,
        "origin0": origin(sheet.setups[0]) if sheet.setups else [0, 0, 0],
        "ops": ops,
        "pockets": [f.id for f in sheet.part.features if isinstance(f, (PocketFeature, SlotFeature))],
        "holes": [f.id for f in sheet.part.features if isinstance(f, (HoleFeature, ThreadFeature))],
    }
