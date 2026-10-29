"""
Планировщик технологии: установы, крепление, порядок операций, инструмент, режимы, стратегии HSMWorks.

Логика рассчитана на 2.5D–3-осевые детали из плиты в тисках на Haas VF-2:
  Установ 1 (верх): торцовка, наружный контур (с заходом в зону захвата), карманы, пазы, отверстия, резьбы, фаски.
  Установ 2 (низ): переворот, торцовка в размер по толщине (снятие зоны захвата), элементы низа, фаски низа.
  Боковые элементы: отдельные установы.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from numcraft import cutting, strategies as S
from numcraft.faces import face_dims
from numcraft.knowledge import tooling
from numcraft.knowledge.machine import Machine, load_machine
from numcraft.knowledge.materials import Material, resolve_material
from numcraft.models import (
    SIDE_RU, Box, ChamferFeature, ContourFeature, FaceFeature, HoleFeature, Operation, Part,
    PocketFeature, Setup, SlotFeature, SurfaceFeature, TechSheet, ThreadFeature, Tool, _n,
)

# Стандартные толщины плит (мм) для автоматического назначения заготовки
PLATE_THICKNESSES = [6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100, 110, 120]
XY_STOCK_ALLOWANCE = 3.0  # на сторону, для пиленой плиты
TOP_ALLOWANCE = 1.0

# Этапы внутри установа (порядок операций)
# торцовка → наружный контур (черновой, чистовой) → карманы/пазы (черновая, углы, чистовая) → 3D →
# отверстия (центровка, сверление, расточка) → фаски → резьба → развёртка
ST_FACE, ST_CONTOUR_R, ST_CONTOUR_F, ST_ROUGH, ST_REST, ST_FINISH, ST_3D, ST_SPOT, ST_DRILL, ST_BORE, ST_CHAMFER, \
    ST_TAP, ST_REAM = (10, 12, 14, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80)

FITS = ("H6", "H7", "H8", "H9")


class Planner:
    def __init__(self, part: Part, machine: Optional[Machine] = None):
        self.part = part
        self.machine = machine or load_machine()
        self.mat: Material = resolve_material(part.material)
        self.g = self.mat.group
        self.assumptions: List[str] = []
        self.questions: List[str] = []
        self._fid = 0
        for f in part.features:
            if not f.id:
                self._fid += 1
                f.id = f"F{self._fid}"

    # ------------------------------------------------------------------ заготовка
    def _stock(self) -> Box:
        p = self.part.size
        if self.part.stock:
            return self.part.stock
        z_need = p.z + TOP_ALLOWANCE + self.machine.vise.recommended_grip_mm + 1.3
        z = next((t for t in PLATE_THICKNESSES if t >= z_need), math.ceil(z_need))
        stock = Box(x=p.x + 2 * XY_STOCK_ALLOWANCE, y=p.y + 2 * XY_STOCK_ALLOWANCE, z=z)
        self.assumptions.append(
            f"Заготовка не задана — принята пиленая плита {stock.fmt()} "
            f"(+{_n(XY_STOCK_ALLOWANCE)} мм на сторону по XY, по Z: {_n(TOP_ALLOWANCE)} мм под торцовку сверху "
            f"+ зона захвата в тисках снизу)."
        )
        return stock

    # ------------------------------------------------------------------ helpers
    def _thick(self, side: str) -> float:
        """Глубина детали от грани до противоположной грани (для сквозных элементов)."""
        return face_dims(side, self.part.size)[2]

    def _xy_positions(self, pts, side: str) -> List[Tuple[float, float]]:
        """Координаты элемента (вид сверху или вид на грань) → СК установа."""
        p = self.part.size
        w, h, _ = face_dims(side, p)
        out = []
        for x, y in pts:
            if side == "bottom":  # переворот вокруг оси X
                y = p.y - y
            if self.part.datum == "center":
                x, y = x - w / 2, y - h / 2
            out.append((round(x, 3), round(y, 3)))
        return out

    def _op(self, title, strategy, tool, cd, stage, fids, params=None, geom: str = "", sel_d: float = 0.0,
            through: bool = False, **kw) -> Operation:
        op = Operation(title=title, strategy=strategy, tool=tool, cutting=cd, stage=stage,
                       feature_ids=list(fids), params=params or {}, geom=geom, **kw)
        depth = (op.z_start or 0) - (op.z_depth or 0)
        op.selection = S.selection(geom, depth=depth, d=sel_d or tool.diameter, through=through)
        return op

    def _end_mill(self, max_d: float, depth: float, why: str, min_d: float = 0.0) -> Optional[Tool]:
        t = tooling.pick_end_mill(self.g, max_d, min_lc=depth, min_d=min_d)
        if t is None:
            self.questions.append(f"Нет концевой фрезы Ø≤{_n(max_d)} в библиотеке для: {why}.")
        return t

    # ------------------------------------------------------------------ операции
    def face_ops(self, allowance: float, width: float, fid: str, bottom: bool) -> List[Operation]:
        if allowance <= 0.02:
            return []
        stock_min = min(self.stock.x, self.stock.y)
        tool = tooling.face_mill() if stock_min >= 30 else self._end_mill(16, 0, "торцовка")
        p = self.mat.face_mill
        ap = min(allowance, p["ap"])
        cd = cutting.face_milling(tool, self.mat, self.machine, ap=ap, width=width) if tool.kind == "face_mill" \
            else cutting.milling(tool, self.mat, self.machine, "pocket", ap=ap)
        n_pass = math.ceil(max(allowance - p["ap_finish"], 0) / (cd.ap or ap)) + (1 if allowance > p["ap_finish"] else 0)
        title = (f"Торцовка в размер по толщине {_n(self.part.size.z)} мм (снять {_n(allowance)} мм)"
                 if bottom else f"Торцовка верха (снять {_n(allowance)} мм)")
        op = self._op(title, S.FACE, tool, cd, ST_FACE, [fid],
                      S.face(tool, cd, allowance, p["ap_finish"]), z_depth=0.0, geom="face")
        op.notes.append(f"Проходов по Z ≈ {max(n_pass, 1)}; последний — чистовой {_n(min(allowance, p['ap_finish']))} мм.")
        if bottom:
            op.notes.append("После торцовки замерить толщину микрометром; при необходимости — доп. проход с коррекцией Z.")
        return [op]

    def contour_ops(self, f: ContourFeature, depth: float, z_top: float = 0.0, band: bool = False) -> List[Operation]:
        ops: List[Operation] = []
        mx = (self.stock.x - (f.length or self.part.size.x)) / 2
        my = (self.stock.y - (f.width or self.part.size.y)) / 2
        allowance = max(mx, my, 0.0)
        # наружные скругления выпуклые — радиус не ограничивает диаметр фрезы
        tool = self._end_mill(16.0, depth + 1, "наружный контур")
        if not tool:
            return ops
        what = "пояса контура (дообработка после переворота)" if band else "наружного контура"
        if allowance > 2.0:
            cd = cutting.milling(tool, self.mat, self.machine, "adaptive", ap=min(depth, tool.flute_length))
            ops.append(self._op(f"Черновая {what}, глубина {_n(depth)} мм", S.ADAPTIVE_2D, tool, cd, ST_CONTOUR_R,
                                [f.id], S.adaptive(tool, cd, self.mat, depth, stock_contours=True), z_depth=-depth,
                                geom="outer_rough"))
        elif allowance > 0.3:
            cd = cutting.milling(tool, self.mat, self.machine, "contour", ap=min(depth, tool.flute_length),
                                 ae=round(allowance - 0.2, 2))
            ops.append(self._op(f"Получистовая {what} (припуск {_n(allowance)} мм)", S.CONTOUR_2D, tool, cd,
                                ST_CONTOUR_R, [f.id], S.contour_light_rough(tool, allowance), z_depth=-depth,
                                geom="outer_walls"))
        cdf = cutting.milling(tool, self.mat, self.machine, "finish_wall", ap=min(depth, tool.flute_length))
        fin = self._op(f"Чистовая {what}", S.CONTOUR_2D, tool, cdf, ST_CONTOUR_F, [f.id],
                       S.contour_finish(tool, cdf, depth, f.tolerance), z_depth=-depth, geom="outer_walls")
        if band:
            fin.notes.append("Перекрытие с поясом установа 1 — 0.3 мм; возможна ступенька 0.01–0.02 мм на стыке.")
        if f.tolerance and f.tolerance <= 0.02:
            fin.notes.append("Жёсткий допуск — рекомендуется отдельная чистовая фреза (новая).")
        ops.append(fin)
        return ops

    def pocket_ops(self, f: PocketFeature) -> List[Operation]:
        ops: List[Operation] = []
        depth = self._thick(f.side) + 0.3 if f.through else f.depth
        narrow = min(f.length, f.width)
        r_corner = f.corner_radius
        rough = self._end_mill(min(16.0, 0.65 * narrow), depth + 1, f"черновая кармана {f.id}")
        if not rough:
            return ops
        fin_max_d = (2 * r_corner - 0.5) if r_corner > 0 else rough.diameter
        finisher = rough if rough.diameter <= fin_max_d + 1e-6 else self._end_mill(fin_max_d, depth + 1,
                                                                                  f"углы R{_n(r_corner)} кармана {f.id}")
        cnt = f" ×{f.count}" if f.count > 1 else ""
        name = f"карман {_n(f.length)}×{_n(f.width)}×{_n(depth)}{cnt}"
        cd = cutting.milling(rough, self.mat, self.machine, "adaptive", ap=min(depth, rough.flute_length))
        ops.append(self._op(f"Черновая: {name}", S.ADAPTIVE_2D, rough, cd, ST_ROUGH, [f.id],
                            S.adaptive(rough, cd, self.mat, depth), z_depth=-depth, geom="pocket_area",
                            through=f.through))
        if finisher and finisher is not rough:
            corner_rest = (rough.diameter / 2 - finisher.diameter / 2)
            if corner_rest > 1.0:
                cdr = cutting.milling(finisher, self.mat, self.machine, "adaptive", ap=min(depth, finisher.flute_length))
                ops.append(self._op(f"Дообработка углов R{_n(r_corner)}: {name}", S.ADAPTIVE_2D, finisher, cdr,
                                    ST_REST, [f.id], S.adaptive(finisher, cdr, self.mat, depth, rest=True),
                                    z_depth=-depth, geom="pocket_corners"))
        fin = finisher or rough
        if not f.through:
            cdf = cutting.milling(fin, self.mat, self.machine, "finish_floor")
            ops.append(self._op(f"Чистовая дна: {name}", S.POCKET_2D, fin, cdf, ST_FINISH, [f.id],
                                S.pocket(fin, cdf, floor_only=True), z_depth=-depth, geom="pocket_floor"))
        cdw = cutting.milling(fin, self.mat, self.machine, "finish_wall", ap=min(depth, fin.flute_length))
        ops.append(self._op(f"Чистовая стенок: {name}", S.CONTOUR_2D, fin, cdw, ST_FINISH, [f.id],
                            S.contour_finish(fin, cdw, depth, f.tolerance), z_depth=-depth, geom="pocket_walls"))
        if r_corner <= 0:
            self.questions.append(
                f"Карман {f.id}: радиус внутренних углов не указан — принят радиус фрезы R{_n(fin.diameter / 2)}. "
                "Острые внутренние углы фрезой не получить.")
        return ops

    def slot_ops(self, f: SlotFeature) -> List[Operation]:
        ops: List[Operation] = []
        depth = self._thick(f.side) + 0.3 if f.through else f.depth
        cnt = f" ×{f.count}" if f.count > 1 else ""
        name = f"паз {_n(f.length)}×{_n(f.width)}×{_n(depth)}{cnt}"
        exact = tooling.pick_end_mill(self.g, f.width, min_lc=depth, min_d=f.width)
        if exact and f.width <= 6 and not f.tolerance:
            cd = cutting.milling(exact, self.mat, self.machine, "slot")
            ops.append(self._op(f"Паз фрезой в размер: {name}", S.SLOT, exact, cd, ST_ROUGH, [f.id],
                                S.slot(exact, cd), z_depth=-depth, geom="slot_area", through=f.through))
            ops[-1].notes.append("Ширина паза = диаметру фрезы; фактический размер +0.01…0.03 мм от биения.")
            return ops
        tool = self._end_mill(0.75 * f.width, depth + 1, f"паз {f.id}")
        if not tool:
            return ops
        cd = cutting.milling(tool, self.mat, self.machine, "adaptive", ap=min(depth, tool.flute_length))
        ops.append(self._op(f"Черновая: {name}", S.ADAPTIVE_2D, tool, cd, ST_ROUGH, [f.id],
                            S.adaptive(tool, cd, self.mat, depth), z_depth=-depth, geom="slot_area",
                            through=f.through))
        if not f.through:
            cdf = cutting.milling(tool, self.mat, self.machine, "finish_floor")
            ops.append(self._op(f"Чистовая дна: {name}", S.POCKET_2D, tool, cdf, ST_FINISH, [f.id],
                                S.pocket(tool, cdf, floor_only=True), z_depth=-depth, geom="slot_area"))
        cdw = cutting.milling(tool, self.mat, self.machine, "finish_wall", ap=min(depth, tool.flute_length))
        ops.append(self._op(f"Чистовая стенок: {name}", S.CONTOUR_2D, tool, cdw, ST_FINISH, [f.id],
                            S.contour_finish(tool, cdw, depth, f.tolerance), z_depth=-depth, geom="slot_walls"))
        return ops

    def _spot(self, fid: str, d_hole: float, positions, chamfer: float = 0.2, z0: float = 0.0) -> Operation:
        tool = tooling.spot_drill()
        cd = cutting.spot_drilling(tool, self.mat, self.machine)
        spot_d = d_hole + 2 * chamfer
        if spot_d <= tool.diameter - 0.5:
            depth = round(spot_d / 2, 2)  # 90°: глубина = D/2
            note = f"центровка с фаской: Ø{_n(spot_d)} на входе"
        else:
            depth = 1.5
            note = "центровка без фаски (отверстие больше центровки)"
        op = self._op(f"Центровка под Ø{_n(d_hole)}", S.DRILL, tool, cd, ST_SPOT, [fid],
                      S.drill("G81", f"{_n(depth)} мм от поверхности входа", None, False),
                      cycle="G81", z_depth=round(z0 - depth, 3), z_start=z0, positions=positions,
                      geom="holes", sel_d=d_hole)
        op.notes.append(note)
        return op

    def _drill_cycle(self, d: float, total_depth: float) -> Tuple[str, Optional[float]]:
        ratio = total_depth / d
        al = self.mat.is_aluminum
        if ratio <= 3:
            return "G81", None
        if ratio <= 5:
            return "G73", round(d * (1.5 if al else 1.0), 1)
        return "G83", round(d * (1.0 if al else 0.5), 1)

    def _drill(self, fid: str, d: float, depth: float, through: bool, positions, purpose: str,
               z0: float = 0.0) -> Operation:
        tool = tooling.drill(d, depth + 0.3 * d + (1.0 if through else 0.0) - z0, self.g)
        tip = 0.3 * d if (tool.point_angle or 140) <= 118 else 0.18 * d
        total = depth + tip + (1.0 if through else 0.0)
        cycle, peck = self._drill_cycle(d, total)
        cd = cutting.drilling(tool, self.mat, self.machine)
        note = f"{_n(round(total, 2))} мм ({'сквозь, с выходом вершины' if through else 'по вершине сверла'})"
        op = self._op(" ".join(x for x in (f"Сверление Ø{_n(d)}", purpose.strip()) if x), S.DRILL, tool, cd, ST_DRILL, [fid],
                      S.drill(cycle, note, peck, through), cycle=cycle, z_depth=round(z0 - total, 2),
                      z_start=z0, positions=positions, peck=peck, geom="holes", sel_d=d)
        return op

    def hole_ops(self, f: HoleFeature, positions) -> List[Operation]:
        ops: List[Operation] = []
        z0 = f.z_start
        depth = f.depth if f.depth else (self._thick(f.side) + z0 if f.through else None)
        if depth is None:
            depth = round(f.diameter * 2, 1)
            self.questions.append(f"Отверстие {f.id} Ø{_n(f.diameter)}: глубина не указана — принято {_n(depth)} мм.")
        fit = (f.fit or "").upper()
        precise = fit in FITS or (f.ra is not None and f.ra <= 1.6)
        d = f.diameter
        cnt = f" ({f.count} шт.)" if f.count > 1 else ""
        if precise and d <= tooling.MAX_DRILL_D:
            d_pre = round(d - tooling.reaming_allowance(d), 1)
            ops.append(self._spot(f.id, d_pre, positions, chamfer=f.chamfer or 0.2, z0=z0))
            ops.append(self._drill(f.id, d_pre, depth + (0 if f.through else 0.3 * d), f.through, positions,
                                   f"под развёртку Ø{_n(d)}{fit}{cnt}", z0=z0))
            rt = tooling.reamer(d, fit or "", depth=depth + (1.5 if f.through else 0) - z0)
            cd = cutting.reaming(rt, self.mat, self.machine)
            rdepth = depth + (1.5 if f.through else 0)
            ops.append(self._op(f"Развёртывание Ø{_n(d)}{fit}{cnt}", S.DRILL, rt, cd, ST_REAM, [f.id],
                                S.reaming(f"{_n(rdepth)} мм"), cycle="G85", z_depth=round(z0 - rdepth, 3),
                                z_start=z0, positions=positions, geom="holes", sel_d=d))
            if not f.through:
                ops[-1].notes.append("Глухое отверстие: сверло углублено на 0.3D под заборный конус развёртки.")
        elif d <= tooling.MAX_TWIST_DRILL_PREFERRED:
            ops.append(self._spot(f.id, d, positions, chamfer=f.chamfer or 0.2, z0=z0))
            ops.append(self._drill(f.id, round(d, 1), depth, f.through, positions, cnt, z0=z0))
            if f.walls > 1:
                ops[-1].notes.append(f"Отверстие через {f.walls} стенки с пустотой между ними: подача на входе во "
                                     "вторую стенку −50 % (увод сверла), G83 с выводом стружки на каждой стенке.")
        else:
            # крупное отверстие — спиральная расточка концевой фрезой
            tool = self._end_mill(min(0.75 * d, 16), depth + 1, f"расточка Ø{_n(d)}", min_d=0.4 * d)
            if tool and d > 1.6 * tool.diameter:
                # большое отверстие из сплошного: сначала адаптивная выборка как круглого кармана
                hd = depth + (0.3 if f.through else 0)
                cdr = cutting.milling(tool, self.mat, self.machine, "adaptive", ap=min(hd, tool.flute_length))
                ops.append(self._op(f"Черновая выборка отверстия Ø{_n(d)}{cnt}", S.ADAPTIVE_2D, tool, cdr, ST_ROUGH,
                                    [f.id], S.adaptive(tool, cdr, self.mat, hd), z_depth=round(z0 - hd, 3),
                                    z_start=z0, positions=positions, geom="hole_area", sel_d=d))
            if tool:
                cd = cutting.milling(tool, self.mat, self.machine, "bore")
                ops.append(self._op(f"Спиральная расточка Ø{_n(d)}{fit}{cnt}", S.BORE, tool, cd,
                                    ST_BORE, [f.id], S.bore(tool, cd, d, True, self.mat),
                                    z_depth=round(z0 - depth - (0.3 if f.through else 0), 3), z_start=z0,
                                    positions=positions, geom="hole_walls", sel_d=d))
                if precise:
                    ops[-1].notes.append(f"Квалитет {fit} спиральной расточкой — на грани; для серий — расточная головка.")
        if f.counterbore:
            cb = f.counterbore
            tool = self._end_mill(min(0.8 * cb.diameter, 16), cb.depth + 1, f"цековка Ø{_n(cb.diameter)}",
                                  min_d=max(d * 0.6, 0.5 * cb.diameter))
            if tool:
                cd = cutting.milling(tool, self.mat, self.machine, "bore")
                ops.append(self._op(f"Цековка Ø{_n(cb.diameter)}×{_n(cb.depth)}{cnt}", S.BORE, tool, cd, ST_BORE,
                                    [f.id], S.bore(tool, cd, cb.diameter, True, self.mat),
                                    z_depth=round(z0 - cb.depth, 3), z_start=z0, positions=positions,
                                    geom="hole_walls", sel_d=cb.diameter))
        return ops

    def thread_ops(self, f: ThreadFeature, positions) -> List[Operation]:
        ops: List[Operation] = []
        d, p = tooling.parse_thread(f.size)
        size = f"M{_n(d)}" + (f"x{_n(p)}" if p != tooling.METRIC_COARSE.get(d, (None,))[0] else "")
        tl = f.depth
        if tl is None:
            tl = self._thick(f.side) + f.z_start if f.through else round(2 * d, 1)
            if not f.through:
                self.questions.append(f"Резьба {f.id} {size}: длина резьбы не указана — принято 2D = {_n(tl)} мм.")
        cnt = f" ({f.count} шт.)" if f.count > 1 else ""
        method = f.method
        if method == "auto":
            method = "tap" if d <= 12 else "thread_mill"
        z0 = f.z_start
        tz = tl + (3 * p if f.through else 0)
        tap = tooling.tap(size, f.through, depth=tz - z0) if method == "tap" else None
        drill_d = (tap.core_drill if tap and tap.core_drill else None) or tooling.tap_drill(d, p)
        # глубина сверления: длина резьбы + заборная часть метчика 3P
        drill_depth = tl if f.through else tl + 3 * p
        ops.append(self._spot(f.id, d, positions, chamfer=0.3, z0=z0))
        ops[-1].title = f"Центровка с фаской под {size}"
        ops.append(self._drill(f.id, drill_d, drill_depth, f.through, positions, f"под резьбу {size}{cnt}", z0=z0))
        if tap is not None:
            tool = tap
            cd = cutting.tapping(tool, self.mat, self.machine)
            ops.append(self._op(f"Нарезание резьбы {size}{cnt}", S.DRILL, tool, cd, ST_TAP, [f.id],
                                S.tapping(p, f"{_n(tz)} мм"), cycle="G84", z_depth=round(z0 - tz, 2), z_start=z0,
                                positions=positions, geom="holes", sel_d=drill_d))
            if not f.through:
                ops[-1].notes.append(f"Запас под стружку и заборный конус: сверление на {_n(3 * p)} мм глубже резьбы.")
            if tool.core_drill and not math.isclose(tool.core_drill, tooling.tap_drill(d, p)):
                ops[-1].notes.append(f"Сверло под резьбу Ø{_n(tool.core_drill)} — по рекомендации каталога ZCC.")
            ops[-1].notes.append("Только жёсткое (синхронное) нарезание, без компенсационного патрона.")
        else:
            tool = tooling.thread_mill(d)
            if tool:
                cd = cutting.milling(tool, self.mat, self.machine, "thread_mill")
                ops.append(self._op(f"Резьбофрезерование {size}{cnt}", S.THREAD, tool, cd, ST_TAP, [f.id],
                                    S.thread_mill(p, tl), z_depth=round(z0 - tl, 3), z_start=z0,
                                    positions=positions, geom="thread"))
            else:
                self.questions.append(f"Нет резьбофрезы для {size} — добавьте в библиотеку или задайте method=tap.")
        return ops

    def chamfer_ops(self, f: ChamferFeature, what: str) -> List[Operation]:
        if f.profile == "round":
            tool = tooling.round_mill(f.size)
            cd = cutting.milling(tool, self.mat, self.machine, "chamfer")
            op = self._op(f"Скругление рёбер R{_n(f.size)} — {what}", S.ROUND_2D, tool, cd, ST_CHAMFER, [f.id],
                          S.corner_round(f.size, tool), z_depth=-(f.size + 0.2), geom="round_edges")
            if f.note:
                op.notes.append(f.note)
            if not tool.article:
                op.notes.append("Фрезы-скругления такого радиуса нет в каталоге ZCC — заказать или сделать "
                                "сферической фрезой 3D-стратегией (Scallop/Contour) по модели.")
            return [op]
        tool = tooling.chamfer_mill()
        cd = cutting.milling(tool, self.mat, self.machine, "chamfer")
        op = self._op(f"Фаска {_n(f.size)}×45° — {what}", S.CHAMFER_2D, tool, cd, ST_CHAMFER, [f.id],
                      S.chamfer(f.size, tool), z_depth=-(f.size + 0.5), geom=f"chamfer_{f.edges}")
        return [op]

    def surface_ops(self, f: SurfaceFeature) -> List[Operation]:
        ops: List[Operation] = []
        depth = f.depth or self.part.size.z / 2
        rough = self._end_mill(min(12.0, (f.width or 50) * 0.5), depth + 1, f"черновая 3D {f.id}")
        if rough:
            cd = cutting.milling(rough, self.mat, self.machine, "adaptive", ap=min(depth, rough.flute_length))
            p = S.adaptive(rough, cd, self.mat, depth)
            p["Stock to leave (припуск)"] = "0.3 мм по поверхности"
            ops.append(self._op(f"Черновая 3D-поверхности {f.id}", S.ADAPTIVE_3D, rough, cd, ST_ROUGH, [f.id], p,
                                z_depth=-depth, notes=[f.description] if f.description else [], geom="surface"))
        r_lim = f.min_concave_radius or 5
        ball = tooling.ball_mill(min(2 * r_lim * 0.9, 10), self.g)
        if ball:
            ra = f.ra or 3.2
            semi = S.scallop_stepover(ball.diameter / 2, ra * 3)
            fin = S.scallop_stepover(ball.diameter / 2, ra)
            cd = cutting.milling(ball, self.mat, self.machine, "ball", ap=0.3, ae=semi)
            cdf = cutting.milling(ball, self.mat, self.machine, "ball", ap=0.1, ae=fin)
            ops.append(self._op("Получистовая 3D", S.PARALLEL_3D, ball, cd, ST_3D, [f.id],
                                {"Stepover": f"{_n(semi)} мм", "Stock to leave": "0.1 мм",
                                 "Pass direction": "под 45° к основным рёбрам"}, z_depth=-depth, geom="surface"))
            ops.append(self._op(f"Чистовая 3D (Ra {_n(ra)})", S.SCALLOP_3D, ball, cdf, ST_3D, [f.id],
                                {"Stepover (по гребешку)": f"{_n(fin)} мм",
                                 "Альтернатива": f"{S.STEEP_SHALLOW_3D} — при крутых стенках > 60°",
                                 "Tolerance": "0.005 мм, Smoothing вкл."}, z_depth=-depth, geom="surface"))
        return ops

    # ------------------------------------------------------------------ установы
    def _holes_in_pockets(self) -> None:
        """Отверстие целиком в дне кармана: вход — от дна (Z = −глубина), а не от верха детали."""
        from numcraft.sketch import _feature_box

        pockets = [(f, _feature_box(f)) for f in self.part.features
                   if isinstance(f, (PocketFeature, SlotFeature)) and not f.through]
        for h in self.part.features:
            if not isinstance(h, (HoleFeature, ThreadFeature)) or not h.positions or h.z_start:
                continue
            r = h.diameter / 2 if isinstance(h, HoleFeature) else tooling.parse_thread(h.size)[0] / 2
            for pk, box in pockets:
                if box is None or pk.side != h.side:
                    continue
                inside = all(box[0] + r <= x <= box[2] - r and box[1] + r <= y <= box[3] - r for x, y in h.positions)
                if inside:
                    h.z_start = -pk.depth
                    if h.through and h.depth and h.depth >= self._thick(h.side) - 1e-6:
                        h.depth = round(self._thick(h.side) - pk.depth, 3)
                    self.assumptions.append(f"{h.id}: отверстие в дне кармана {pk.id} — вход с Z{_n(-pk.depth)}.")
                    break

    def _merge_through(self) -> None:
        """Меньше установов: сквозной элемент, который один «держит» сторону, переносим на противоположную
        сторону, где установ всё равно нужен (низ → верх; бок → противоположный бок с элементами)."""
        from numcraft.faces import face_dims as fd

        opposite = {"bottom": "top", "front": "back", "back": "front", "left": "right", "right": "left"}
        feats = [f for f in self.part.features if not isinstance(f, (ContourFeature, FaceFeature, ChamferFeature))]

        def movable(f) -> bool:
            return isinstance(f, (HoleFeature, ThreadFeature, PocketFeature, SlotFeature)) and \
                getattr(f, "through", False) and not getattr(f, "z_start", 0) and \
                not (isinstance(f, HoleFeature) and f.counterbore)

        for side, opp in opposite.items():
            here = [f for f in feats if f.side == side]
            there = [f for f in feats if f.side == opp]
            if not here or not all(movable(f) for f in here):
                continue
            if opp != "top" and not there:
                continue
            w, _, _ = fd(side, self.part.size)
            for f in here:
                if side != "bottom":  # зеркально по ширине грани (вид с противоположной стороны)
                    if getattr(f, "positions", None):
                        f.positions = [(round(w - u, 3), v) for u, v in f.positions]
                    if getattr(f, "center", None):
                        f.center = (round(w - f.center[0], 3), f.center[1])
                f.side = opp
            self.assumptions.append(f"Сквозные элементы стороны «{SIDE_RU[side]}» делаются с «{SIDE_RU[opp]}» "
                                    "— на один установ меньше.")

    def plan(self) -> TechSheet:
        part = self.part
        self._merge_through()
        self._holes_in_pockets()
        self.stock = stock = self._stock()
        ps = part.size
        vise = self.machine.vise

        extra_z = round(stock.z - ps.z, 3)
        if extra_z < 0 or stock.x < ps.x - 0.01 or stock.y < ps.y - 0.01:
            raise ValueError("Заготовка меньше детали.")
        top_allow = 0.0 if extra_z <= 0.05 else (extra_z / 2 if extra_z < 2 else TOP_ALLOWANCE)
        bottom_allow = round(extra_z - top_allow, 3)
        margin_xy = max(stock.x - ps.x, stock.y - ps.y) / 2

        contours = [f for f in part.features if isinstance(f, ContourFeature)]
        if not contours and margin_xy > 0.25:
            contours = [ContourFeature(id="K", length=ps.x, width=ps.y)]
            self.assumptions.append("Наружный контур (габарит детали) обрабатывается из заготовки.")
        # высота, которая остаётся для захвата в тисках
        grip = vise.recommended_grip_mm if bottom_allow - 1.3 >= vise.recommended_grip_mm \
            else max(vise.min_grip_mm, bottom_allow - 1.3)
        contour_depth_1 = round(min(ps.z + 0.3, ps.z + bottom_allow - grip - 1.0), 2)
        if contours and bottom_allow > 0.02:
            # высокая стенка: если ни одна фреза Ø≤16 не достаёт с L/D ≤ 4 — контур в два пояса (с переворотом)
            reach = tooling.pick_end_mill(self.g, 16.0, min_lc=contour_depth_1 + 1)
            if reach and (reach.flute_length < contour_depth_1 + 1 or contour_depth_1 / reach.diameter > 4):
                longest = max((t.flute_length for t in tooling.end_mills(self.g) if t.diameter >= 10), default=0)
                contour_depth_1 = round(min(contour_depth_1, max(longest - 1, ps.z / 2 + 1)), 2)

        by_side: Dict[str, list] = {}
        for f in part.features:
            if isinstance(f, ContourFeature):
                continue
            by_side.setdefault(f.side, []).append(f)

        setups: List[Setup] = []

        # --- Установ 1: верх
        s1_ops: List[Operation] = []
        face_feats = [f for f in by_side.get("top", []) if isinstance(f, FaceFeature)]
        if top_allow > 0.02:
            s1_ops += self.face_ops(top_allow, stock.y, face_feats[0].id if face_feats else "A", bottom=False)
        elif face_feats:
            self.questions.append("Торцовка задана, но заготовка по толщине без припуска — торцовка пропущена.")
        for c in contours:
            if c.side == "top":
                s1_ops += self.contour_ops(c, contour_depth_1)
        s1_ops += self._feature_ops(by_side.get("top", []), "top")
        clamp_y = min(stock.x, stock.y)
        wh1 = [
            f"{vise.name}: зажим по стороне {_n(clamp_y)} мм, захват {_n(grip)} мм по высоте, "
            f"заготовка на параллелях; над губками ≈ {_n(round(stock.z - grip, 1))} мм.",
            "Губки рифлёные или гладкие стальные; заготовку осадить на параллели (киянкой), проверить щупом 0.02 мм.",
        ]
        if clamp_y > vise.max_opening_mm:
            wh1 = [f"Заготовка шире раскрытия тисков ({_n(vise.max_opening_mm)} мм): крепление прихватами к столу "
                   "или к приспособлению-плите, с подкладками; контур обходить без прихватов (перестановка)."]
        through = any(getattr(f, "through", False) for f in part.features if not isinstance(f, ContourFeature))
        if through and bottom_allow < 2.5:
            wh1.append("Снизу почти нет припуска: параллели развести так, чтобы под сквозными элементами был зазор.")
        s1 = Setup(number=1, side="top", title="Установ 1 — верх (сторона A)", wcs="G54",
                   stock_top=round(top_allow, 3), z_shift=round(top_allow, 3), workholding=wh1,
                   datum=self._datum_text(top_allow, flip=False), operations=s1_ops)
        if contours and contour_depth_1 < ps.z:
            s1.notes.append(
                f"Контур в установе 1 — на глубину {_n(contour_depth_1)} мм (мало заготовки снизу для захвата); "
                "остаток контура — в установе 2.")
        setups.append(s1)

        # --- Установ 2: низ
        bottom_feats = by_side.get("bottom", [])
        explicit_bottom = any(isinstance(f, ChamferFeature) and f.side == "bottom" for f in part.features)
        # фаска «по контуру» из описания — и на нижние кромки; из STEP/с явным низом — только где указано
        chamfers_both = [] if explicit_bottom else [
            f for f in part.features if isinstance(f, ChamferFeature) and f.edges in ("outer", "all")
            and f.side == "top" and not f.note.startswith("из STEP")]
        if bottom_allow > 0.02 or bottom_feats:
            s2_ops: List[Operation] = []
            s2_ops += self.face_ops(bottom_allow, stock.y, "B", bottom=True)
            if contours and contour_depth_1 < ps.z:
                band = round(ps.z - contour_depth_1 + 0.3, 2)
                s2_ops += self.contour_ops(contours[0], band, band=True)
            s2_ops += self._feature_ops(bottom_feats, "bottom")
            for ch in chamfers_both:
                s2_ops += self.chamfer_ops(ch, "кромки низа")
            open_top = [f for f in by_side.get("top", []) if isinstance(f, (PocketFeature, SlotFeature))]
            wh2 = [
                "Переворот вокруг оси X (передняя грань уходит назад).",
                f"{vise.name}: зажим по обработанным боковым граням, гладкие или мягкие губки; "
                "под обработанный верх — чистые параллели.",
            ] + ([f"Параллели — под сплошные участки верха (стенки), не под паз/карман "
                  f"{', '.join(f.id for f in open_top)}: иначе деталь прогнётся при торцовке."] if open_top else []) + [
                f"Захват ≥ {_n(vise.min_grip_mm)} мм; деталь выступает над губками на {_n(round(bottom_allow + 2, 1))} мм "
                "и больше (торцовка не должна задеть губки).",
            ]
            setups.append(Setup(number=2, side="bottom", title="Установ 2 — низ (сторона B, переворот)",
                                wcs="G55", stock_top=round(bottom_allow, 3), workholding=wh2, datum=self._datum_text(bottom_allow, flip=True), operations=s2_ops))

        # --- боковые установы: деталь на бок / на торец, обрабатываемая грань вверх
        for side in ("front", "back", "left", "right"):
            feats = by_side.get(side, [])
            if not feats:
                continue
            ops = self._feature_ops(feats, side)
            wcs = f"G{54 + len(setups)}" if len(setups) < 6 else "G54.1 P1"
            w, h, depth = face_dims(side, ps)
            name = SIDE_RU[side]
            if side in ("front", "back"):
                hold = [f"Деталь на бок, {name} вверх: зажим по верхней и нижней плоскостям (обработаны), "
                        f"губки по {_n(ps.z)} мм, длина в губках {_n(ps.x)} мм.",
                        f"Деталь стоит на параллелях гранью «{SIDE_RU['back' if side == 'front' else 'front']}»; "
                        f"в губках ≥ {_n(round(depth / 2))} мм (половина высоты), над губками 5–10 мм — "
                        "элементы уходят внутрь детали, губки не мешают."]
            else:
                hold = [f"Деталь на торец, {name} вверх: зажим по передней и задней граням "
                        f"({_n(ps.y)} мм) или по верху/низу ({_n(ps.z)} мм) — что шире.",
                        f"Деталь стоит на торце (высота {_n(depth)} мм): в губках ≥ {_n(round(depth / 2))} мм, "
                        "над губками 5–10 мм; при высоте > 120 мм — угольник или тиски с поворотной губкой."]
            hold.append("Упор по обработанной грани; перпендикулярность базы проверить индикатором ≤ 0.02 мм.")
            setups.append(Setup(
                number=len(setups) + 1, side=side, title=f"Установ {len(setups) + 1} — {name}", wcs=wcs,
                workholding=hold,
                datum=[f"{wcs}: X0 Y0 — " + ("центр грани" if part.datum == "center" else "левый нижний угол грани")
                       + f" «{name}» (вид на грань: X вдоль грани {_n(w)} мм, Y по высоте {_n(h)} мм).",
                       "Z0 — плоскость грани (обработана, касание щупом).",
                       "HSMWorks: новый Setup, ось Z — по нормали к этой грани, WCS — Model box point "
                       + ("«Top center»" if part.datum == "center" else "«Top», левый нижний угол") + "."],
                operations=ops))

        tools = self._finalize(setups)
        sheet = TechSheet(part=part, machine=self.machine.name, material=self.mat.name, stock=stock, setups=setups,
                          tools=tools, assumptions=self.assumptions, questions=self.questions)
        return sheet

    def _datum_text(self, allowance: float, flip: bool) -> List[str]:
        if not flip:
            xy = ("G54: X0 Y0 — центр заготовки: ощупать заготовку щупом с двух сторон по X и по Y"
                  if self.part.datum == "center" else
                  f"G54: X0 Y0 — левый передний угол детали (щуп по заготовке, затем сместить на припуск "
                  f"+{_n(XY_STOCK_ALLOWANCE)} мм внутрь)")
            z = (f"Z0 — верх заготовки (касание фрезой/щупом). Торцовка снимает {_n(allowance)} мм — "
                 f"верх детали будет на Z−{_n(allowance)}; все глубины в таблицах — от этого Z0."
                 if allowance > 0.02 else "Z0 — верх заготовки (он же верх детали, припуска нет).")
            cam = ("HSMWorks: Setup → Work Coordinate System — Stock box point, "
                   + ("«Top center» (верх, центр)" if self.part.datum == "center" else "«Top», левый передний угол"))
            return [xy, z, cam]
        xy = ("G55: X0 Y0 — центр детали по обработанному контуру (щуп по двум парам сторон)"
              if self.part.datum == "center" else "G55: X0 Y0 — левый передний угол по обработанному контуру")
        z = (f"Z0 — низ детали (готовый размер по толщине {_n(self.part.size.z)} мм): деталь на параллелях, "
             f"Z0 = верх параллелей + {_n(self.part.size.z)} мм; необработанная поверхность сейчас выше на "
             f"{_n(allowance)} мм — её снимает торцовка.")
        cam = ("HSMWorks: новый Setup с переворотом (Orientation: Z — вниз по модели), WCS — Model box point "
               + ("«Top center»" if self.part.datum == "center" else "«Top», левый передний угол"))
        return [xy, z, cam]

    def _feature_ops(self, feats, side: str) -> List[Operation]:
        ops: List[Operation] = []
        for f in feats:
            pos = self._xy_positions(getattr(f, "positions", []) or [], side)
            if isinstance(f, PocketFeature):
                ops += self.pocket_ops(f)
            elif isinstance(f, SlotFeature):
                ops += self.slot_ops(f)
            elif isinstance(f, HoleFeature):
                ops += self.hole_ops(f, pos)
            elif isinstance(f, ThreadFeature):
                ops += self.thread_ops(f, pos)
            elif isinstance(f, ChamferFeature):
                what = {"outer": "наружный контур", "all": "все кромки", "pockets": "кромки карманов",
                        "holes": "кромки отверстий"}[f.edges]
                ops += self.chamfer_ops(f, what)
            elif isinstance(f, SurfaceFeature):
                ops += self.surface_ops(f)
            elif isinstance(f, FaceFeature):
                continue
            if isinstance(f, (HoleFeature, ThreadFeature)) and f.positions and len(f.positions) != f.count:
                self.questions.append(f"{f.id}: указано {f.count} шт., а координат {len(f.positions)}.")
        return ops

    def _finalize(self, setups: List[Setup]) -> List[Tool]:
        """Сортировка операций, объединение одинаковых, нумерация T."""
        registry: Dict[tuple, Tool] = {}
        order: List[tuple] = []
        n = 0
        for s in setups:
            ops = sorted(s.operations, key=lambda o: o.stage)  # стабильная сортировка сохраняет порядок признаков
            merged: List[Operation] = []
            for op in ops:
                prev = next((m for m in merged if m.stage == op.stage and m.cycle and m.cycle == op.cycle
                             and m.tool.key() == op.tool.key() and m.z_depth == op.z_depth
                             and m.z_start == op.z_start), None)
                if prev is not None:
                    prev.feature_ids += [i for i in op.feature_ids if i not in prev.feature_ids]
                    prev.positions += op.positions
                    if op.title != prev.title:
                        prev.title += f"; {op.title}"
                    continue
                merged.append(op)
            # внутри этапа — группировка по инструменту (меньше смен)
            merged = _group_by_tool(merged)
            for op in merged:
                k = op.tool.key()
                if k not in registry:
                    registry[k] = op.tool.model_copy()
                    order.append(k)
                n += 1
                op.number = n
            s.operations = merged
        for i, k in enumerate(order, 1):
            registry[k].number = i
        for s in setups:
            for op in s.operations:
                op.tool = op.tool.model_copy(update={"number": registry[op.tool.key()].number})
        tools = [registry[k] for k in order]
        for t in tools:
            t.stickout = _stickout(t, setups)
        return tools


def _group_by_tool(ops: List[Operation]) -> List[Operation]:
    out: List[Operation] = []
    for stage in sorted({o.stage for o in ops}):
        chunk = [o for o in ops if o.stage == stage]
        keys: List[tuple] = []
        for o in chunk:
            if o.tool.key() not in keys:
                keys.append(o.tool.key())
        for k in keys:
            out += [o for o in chunk if o.tool.key() == k]
    return out


def _stickout(tool: Tool, setups: List[Setup]) -> float:
    deepest = 0.0
    for s in setups:
        for op in s.operations:
            if op.tool.key() == tool.key() and op.z_depth is not None:
                deepest = max(deepest, -op.z_depth)
    if tool.kind == "chamfer_mill":
        return round(deepest + 15, 0)
    if tool.kind in ("end_mill", "ball_mill", "thread_mill"):
        return round(max(tool.flute_length, deepest) + 5, 0)
    if tool.kind in ("drill", "reamer", "tap"):
        return round(deepest + 10, 0)
    if tool.kind == "spot_drill":
        return round(deepest + 15, 0)
    return 0.0


def plan_part(part: Part, machine: Optional[Machine] = None) -> TechSheet:
    from numcraft.risks import assess

    planner = Planner(part, machine)
    sheet = planner.plan()
    sheet.risks = assess(sheet, planner.mat, planner.machine)
    return sheet
