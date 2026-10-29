"""
Короткий черновик УП (FANUC / Haas NGC).

Что генерируется полностью: шапка, смены инструмента, G43, торцовка зигзагом, циклы
G81/G73/G83/G84/G85 по заданным координатам. Фрезерные операции (Adaptive, Contour, Pocket, Bore,
фаски, 3D) — каркас с вызовом инструмента и меткой, куда вставить траекторию из постпроцессора HSMWorks.

Комментарии — латиницей в верхнем регистре: стойки FANUC не отображают кириллицу.
"""
from __future__ import annotations

import math
from typing import List, Literal, Optional

from numcraft.models import Operation, Setup, TechSheet, Tool

Dialect = Literal["fanuc", "haas"]

_TR = str.maketrans({
    "а": "A", "б": "B", "в": "V", "г": "G", "д": "D", "е": "E", "ё": "E", "ж": "ZH", "з": "Z", "и": "I", "й": "Y",
    "к": "K", "л": "L", "м": "M", "н": "N", "о": "O", "п": "P", "р": "R", "с": "S", "т": "T", "у": "U", "ф": "F",
    "х": "KH", "ц": "TS", "ч": "CH", "ш": "SH", "щ": "SCH", "ъ": "", "ы": "Y", "ь": "", "э": "E", "ю": "YU", "я": "YA",
    "×": "X", "Ø": "D", "ø": "D", "°": "DEG", "(": " ", ")": " ", "±": "+-",
})

STRATEGY_EN = {
    "face": "FACE", "adaptive": "2D ADAPTIVE", "pocket": "2D POCKET", "contour": "2D CONTOUR", "slot": "SLOT",
    "bore": "BORE", "thread": "THREAD MILL", "chamfer": "CHAMFER", "drill": "DRILL", "3d": "3D",
}


def ascii_comment(text: str) -> str:
    s = text.lower().translate(_TR).upper()
    s = "".join(ch if ch.isascii() and (ch.isalnum() or ch in " .,-+=/*#:") else " " for ch in s)
    return " ".join(s.split())[:60]


def num(v: float) -> str:
    """Формат FANUC: всегда с десятичной точкой (10 → '10.', -3.5 → '-3.5')."""
    s = f"{v:.3f}".rstrip("0")
    if s in ("-0.", "-0"):
        s = "0."
    return s if "." in s else s + "."


def tool_en(t: Tool) -> str:
    d = num(t.diameter).rstrip(".")
    return {
        "face_mill": f"FACE MILL D{d}",
        "end_mill": f"END MILL D{d} Z{t.flutes} LC{num(t.flute_length).rstrip('.')}",
        "ball_mill": f"BALL MILL D{d}",
        "spot_drill": f"SPOT DRILL D{d} 90DEG",
        "drill": f"DRILL D{d}",
        "tap": f"TAP {t.thread or 'M' + d}",
        "reamer": f"REAMER D{d}",
        "chamfer_mill": f"CHAMFER MILL D{d} 90DEG",
        "thread_mill": f"THREAD MILL D{d}",
    }.get(t.kind, f"{t.kind.upper()} D{d}")


def _strategy_key(op: Operation) -> str:
    s = op.strategy.lower()
    for k in ("face", "adaptive clearing 3d", "parallel", "scallop", "chamfer", "adaptive", "pocket", "contour",
              "slot", "bore", "thread", "drill"):
        if s.startswith(k) or k in s.split(" (")[0]:
            return {"adaptive clearing 3d": "3d", "parallel": "3d", "scallop": "3d"}.get(k, k)
    return "contour"


class _Writer:
    def __init__(self, dialect: Dialect):
        self.d = dialect
        self.lines: List[str] = []

    def __call__(self, line: str):
        self.lines.append(line)

    def home_z(self):
        if self.d == "haas":
            self("G53 G49 Z0.")
        else:
            self("G91 G28 Z0.")
            self("G90")


def _face_body(w: _Writer, op: Operation, sheet: TechSheet, setup: Setup, stock_top: float, clear: float,
               zs: float = 0.0):
    part, stock = sheet.part, sheet.stock
    r = op.tool.diameter / 2
    step = op.tool.diameter * 0.7
    mx, my = (stock.x - part.size.x) / 2, (stock.y - part.size.y) / 2
    x0, x1, y0, y1 = -mx, part.size.x + mx, -my, part.size.y + my
    if part.datum == "center":
        x0, x1 = x0 - part.size.x / 2, x1 - part.size.x / 2
        y0, y1 = y0 - part.size.y / 2, y1 - part.size.y / 2
    xs, xe = x0 - r - 5, x1 + r + 5
    ys = [y0 + r - step]
    while ys[-1] + r < y1:
        ys.append(ys[-1] + step)
    ap = op.cutting.ap or stock_top
    finish = min(0.3, stock_top)
    # те же уровни, что в техкарте: черновые по ap до припуска finish, затем чистовой в Z0
    levels: List[float] = []
    z = stock_top
    while z - finish > 1e-6:
        z = max(finish, z - ap)
        levels.append(round(z, 3))
    if not levels or levels[-1] != 0.0:
        levels.append(0.0)
    f = num(round(op.cutting.feed))
    for lv in levels:
        w(f"(FACE PASS Z{num(lv - zs)})")
        w(f"G00 X{num(xs)} Y{num(ys[0])}")
        w(f"G00 Z{num(lv - zs + 2)}")
        w(f"G01 Z{num(lv - zs)} F{num(round(op.cutting.feed / 2))}")
        left = True
        for i, y in enumerate(ys):
            if i:
                w(f"G01 Y{num(round(y, 3))}")
            w(f"G01 X{num(xe if left else xs)} F{f}")
            left = not left
        w(f"G00 Z{num(clear)}")


def _cycle_body(w: _Writer, op: Operation, clear: float):
    c = op.cutting
    z = num(op.z_depth or 0)
    rr = 5.0 if op.cycle == "G84" else 2.0
    if not op.positions:
        w("(NO HOLE COORDINATES IN INPUT - ADD X Y AND REMOVE THIS LINE)")
        w(f"(G98 {op.cycle} X... Y... Z{z} R{num(op.z_start + rr)} F{num(round(c.feed, 2))})")
        return
    x, y = op.positions[0]
    w(f"G00 X{num(x)} Y{num(y)}")
    feed = num(round(c.feed, 2)) if op.cycle == "G84" else num(round(c.feed))
    extra = ""
    if op.cycle in ("G73", "G83") and op.peck:
        extra = f" Q{num(op.peck)}"
    if op.cycle == "G84" and w.d == "fanuc":
        w(f"M29 S{c.rpm}")
    w(f"G98 {op.cycle} X{num(x)} Y{num(y)} Z{z} R{num(op.z_start + rr)}{extra} F{feed}")
    for x, y in op.positions[1:]:
        w(f"X{num(x)} Y{num(y)}")
    w("G80")


def generate(sheet: TechSheet, dialect: Dialect = "fanuc", program_start: int = 1001) -> str:
    """Черновик УП: отдельная программа на каждый установ."""
    w = _Writer(dialect)
    name = ascii_comment(sheet.part.name) or "PART"
    mat = ascii_comment(sheet.material)
    w("%")
    for idx, setup in enumerate(sheet.setups):
        prog = program_start + idx
        wcs = setup.wcs
        w(f"O{prog} ({name} OP{setup.number})")
        w(f"(NUMCRAFT DRAFT - {dialect.upper()} - VERIFY IN HSMWORKS SIM)")
        w(f"(MATERIAL {mat})")
        w(f"(STOCK {num(sheet.stock.x).rstrip('.')}X{num(sheet.stock.y).rstrip('.')}X{num(sheet.stock.z).rstrip('.')})")
        w(f"(SETUP {setup.number} {setup.side.upper()} - {wcs} - Z0 TOP OF PART)")
        seen = []
        for op in setup.operations:
            if op.tool.number not in seen:
                seen.append(op.tool.number)
                w(f"(T{op.tool.number} {tool_en(op.tool)})")
        w("G90 G17 G21 G40 G49 G80")
        w.home_z()

        stock_top = setup.stock_top
        zs = setup.z_shift  # Z0 установа относительно верха детали (установ 1 — верх заготовки)
        clear = math.ceil(stock_top - zs + 10)

        current: Optional[int] = None
        for op in setup.operations:
            op = op.model_copy(update={"z_depth": None if op.z_depth is None else round(op.z_depth - zs, 3),
                                       "z_start": round(op.z_start - zs, 3)})
            key = _strategy_key(op)
            w("")
            w(f"(OP {op.number} {STRATEGY_EN.get(key, key.upper())} - {tool_en(op.tool)})")
            c = op.cutting
            if current != op.tool.number:
                if current is not None:
                    w("M09")
                    w("M05")
                    w.home_z()
                    w("M01")
                w(f"T{op.tool.number} M06")
                first = op.positions[0] if op.positions else (0.0, 0.0)
                w(f"G00 G90 {wcs} X{num(first[0])} Y{num(first[1])}")
                # FANUC: при жёстком нарезании шпиндель включает M29, без M03
                w(f"S{c.rpm}" if op.tool.kind == "tap" and dialect == "fanuc" else f"S{c.rpm} M03")
                w(f"G43 H{op.tool.number:02d} Z{num(clear + 40)} M08")
                w(f"G00 Z{num(clear)}")
                current = op.tool.number
            elif op.tool.kind != "tap":
                w(f"S{c.rpm} M03")
            if key == "face":
                _face_body(w, op, sheet, setup, stock_top, clear, zs)
                continue
            elif op.cycle:
                _cycle_body(w, op, clear)
            else:
                w(f"(*** INSERT HSMWORKS TOOLPATH: {STRATEGY_EN.get(key, key.upper())} Z{num(op.z_depth or 0)} ***)")
                w(f"(S{c.rpm} F{num(round(c.feed))})")
            w(f"G00 Z{num(clear)}")
        w("M09")
        w("M05")
        w.home_z()
        if dialect == "haas":
            w("G53 Y0.")
        else:
            w("G91 G28 Y0.")
            w("G90")
        w("M30")
        if idx < len(sheet.setups) - 1:
            w("")
    w("%")
    return "\n".join(w.lines) + "\n"

