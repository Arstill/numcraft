"""Техкарта: вывод в Markdown (русский) и JSON."""
from __future__ import annotations

from typing import Dict, List

from numcraft.models import Operation, TechSheet, _n

LEVEL_MARK = {"высокий": "ВЫСОКИЙ", "средний": "средний", "низкий": "низкий"}


def _v(x) -> str:
    return "—" if x is None else _n(x) if isinstance(x, float) else str(x)


def _feed(op: Operation) -> str:
    f = op.cutting.feed
    return f"{f:.2f}".rstrip("0").rstrip(".") if op.tool.kind == "tap" else str(int(round(f)))


def _fz(op: Operation) -> str:
    c = op.cutting
    if c.f_rev is not None and op.tool.kind in ("drill", "spot_drill", "tap", "reamer"):
        return f"{_n(c.f_rev)} мм/об"
    return f"{_n(c.fz)} мм/зуб" if c.fz else "—"


def to_markdown(sheet: TechSheet, details: bool = True) -> str:
    p = sheet.part
    out: List[str] = []
    w = out.append
    w(f"# Техкарта: {p.name}")
    w("")
    w(f"- **Станок:** {sheet.machine}, FANUC-совместимая стойка")
    w(f"- **Материал:** {sheet.material}")
    w(f"- **Деталь:** {p.size.fmt()}; **заготовка:** {sheet.stock.fmt()}; **кол-во:** {p.quantity} шт.")
    if p.general_tolerance:
        w(f"- **Общие допуски:** {p.general_tolerance}")
    w(f"- **Установов:** {len(sheet.setups)}, **операций:** {sum(len(s.operations) for s in sheet.setups)}, "
      f"**инструментов:** {len(sheet.tools)}")
    w("")

    if sheet.risks:
        w("## Риски и замечания")
        w("")
        w("| Уровень | Тема | Что не так | Что делать |")
        w("|---|---|---|---|")
        for r in sheet.risks:
            w(f"| {LEVEL_MARK[r.level]} | {r.topic} | {r.message} | {r.action} |")
        w("")
    if sheet.questions:
        w("## Вопросы к чертежу (приняты допущения)")
        w("")
        for q in sheet.questions:
            w(f"- {q}")
        w("")
    if sheet.assumptions:
        w("## Допущения")
        w("")
        for a in sheet.assumptions:
            w(f"- {a}")
        w("")

    for s in sheet.setups:
        w(f"## {s.title}")
        w("")
        w("**Крепление:**")
        for x in s.workholding:
            w(f"- {x}")
        w("")
        w("**Нуль детали:**")
        for x in s.datum:
            w(f"- {x}")
        for x in s.notes:
            w(f"- {x}")
        w("")
        w("| Оп. | Операция | Стратегия HSMWorks | T | S, об/мин | F, мм/мин | ap, мм | ae, мм | Vc, м/мин | Подача |")
        w("|---|---|---|---|---|---|---|---|---|---|")
        for op in s.operations:
            w(f"| {op.number} | {op.title} | {op.strategy}{' ' + op.cycle if op.cycle else ''} | T{op.tool.number} | "
              f"{op.cutting.rpm} | {_feed(op)} | {_v(op.cutting.ap)} | {_v(op.cutting.ae)} | {_n(op.cutting.vc)} | "
              f"{_fz(op)} |")
        w("")
        if details:
            for op in s.operations:
                w(f"### Оп. {op.number}. {op.title}")
                w("")
                w(f"- **Стратегия:** {op.strategy}")
                w(f"- **Инструмент:** T{op.tool.number} — {op.tool.label()}, вылет ≈ {_n(op.tool.stickout)} мм"
                  if op.tool.stickout else f"- **Инструмент:** T{op.tool.number} — {op.tool.label()}")
                if op.z_depth is not None:
                    w(f"- **Глубина:** Z{_n(op.z_depth)}")
                if op.positions:
                    pts = ", ".join(f"({_n(x)}; {_n(y)})" for x, y in op.positions[:12])
                    more = f" … всего {len(op.positions)}" if len(op.positions) > 12 else ""
                    w(f"- **Точки (X; Y):** {pts}{more}")
                for k, v in op.params.items():
                    w(f"- {k}: {v}")
                plunge = f", врезание {int(op.cutting.plunge_feed)} мм/мин" if op.cutting.plunge_feed else ""
                pw = f", мощность ≈ {_n(op.cutting.power_kw)} кВт" if op.cutting.power_kw else ""
                w(f"- **Режим:** S{op.cutting.rpm} F{_feed(op)}{plunge}{pw}; {op.cutting.coolant}")
                if op.cutting.limits:
                    w(f"- **Ограничено:** {'; '.join(op.cutting.limits)}")
                for n in op.notes:
                    w(f"- {n}")
                w("")

    w("## Инструментальная карта")
    w("")
    w("| T / H / D | Инструмент | Ø, мм | z | Lc, мм | Вылет, мм | Материал | Операции |")
    w("|---|---|---|---|---|---|---|---|")
    uses: Dict[int, List[str]] = {}
    for s in sheet.setups:
        for op in s.operations:
            uses.setdefault(op.tool.number, []).append(str(op.number))
    for t in sheet.tools:
        mat = t.tool_material + (f", {t.coating}" if t.coating else "")
        w(f"| T{t.number} / H{t.number} / D{t.number} | {t.label()} | {_n(t.diameter)} | {t.flutes} | "
          f"{_v(t.flute_length or None)} | {_v(t.stickout or None)} | {mat} | {', '.join(uses.get(t.number, []))} |")
    w("")
    w("> Режимы — стартовые для Haas VF-2. Первую деталь вести с коррекцией подачи 70–80 % и контролем нагрузки "
      "шпинделя. Траектории формирует HSMWorks; обязательна симуляция в HSMWorks перед выводом УП.")

    if sheet.gcode:
        w("")
        w("## Черновик УП")
        w("")
        w("```gcode")
        w(sheet.gcode.rstrip())
        w("```")
    return "\n".join(out) + "\n"


def to_json(sheet: TechSheet) -> str:
    return sheet.model_dump_json(indent=2)
