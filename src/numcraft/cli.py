"""
Командная строка помощника технолога.

  python -m numcraft plan "Плита 120х80х20 6061, карман 60х40 гл. 8 R5, 4 отв. Ø6.6 сквозные по углам 10" --gcode
  python -m numcraft plan --step part.step --drawing part.pdf --material 7075 -o techsheet.md
  python -m numcraft step part.step
  python -m numcraft cut --material "сталь 45" --tool end_mill --d 10 --op adaptive
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from numcraft import cutting
from numcraft.knowledge import tooling
from numcraft.knowledge.machine import load_machine
from numcraft.knowledge.materials import UnknownMaterial, all_materials, resolve_material
from numcraft.models import _n


def _stock(s: str):
    parts = s.lower().replace("х", "x").replace("×", "x").split("x")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Заготовка в формате 126x86x30")
    return [float(p.replace(",", ".")) for p in parts]


def cmd_plan(a) -> int:
    from numcraft.pipeline import InputError, Inputs, run
    from numcraft.techsheet import to_json, to_markdown

    text = " ".join(a.text) if a.text else None
    if text == "-":
        text = sys.stdin.read()
    try:
        res = run(Inputs(text=text, step_path=a.step, drawing_path=a.drawing, part_json=a.json,
                         material=a.material, name=a.name, stock=a.stock),
                  gcode=a.gcode, dialect=a.dialect, max_rpm=a.rpm)
    except InputError as e:
        print("Не хватает данных для техкарты:", file=sys.stderr)
        for m in e.missing:
            print(f"  • {m}", file=sys.stderr)
        return 2
    md = to_markdown(res.sheet, details=not a.brief)
    if res.step_summary and not a.brief:
        md = md.replace("\n## ", "\n## Анализ STEP\n\n```\n" + res.step_summary + "\n```\n\n## ", 1)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Техкарта: {a.out}")
    else:
        print(md)
    if a.json_out:
        Path(a.json_out).write_text(to_json(res.sheet), encoding="utf-8")
        print(f"JSON: {a.json_out}")
    if a.nc and res.sheet.gcode:
        Path(a.nc).write_text(res.sheet.gcode, encoding="utf-8")
        print(f"УП: {a.nc}")
    return 0


def cmd_step(a) -> int:
    from numcraft.parsers.step import analyze_step_file, summary_ru

    print(summary_ru(analyze_step_file(a.file)))
    return 0


def cmd_drawing(a) -> int:
    from numcraft.parsers.drawing import analyze_drawing

    info = analyze_drawing(a.file)
    print(f"Чертёж: {a.file}")
    print(f"Материал: {info.material or info.unsupported_material or '—'}")
    print(f"Общие допуски: {info.general_tolerance or '—'}")
    print("Квалитеты: " + (", ".join(f"Ø{_n(d)}{f}" + (f" ×{c}" if c > 1 else "") for d, f, c in info.fits) or "—"))
    print("Резьбы: " + (", ".join(f"{s}" + (f" ×{c}" if c > 1 else "") for s, c in info.threads) or "—"))
    print("Ra: " + (", ".join(_n(r) for r in info.ra_values) or "—"))
    for w in info.warnings:
        print(f"! {w}")
    return 0


def cmd_cut(a) -> int:
    mat = resolve_material(a.material)
    machine = load_machine(max_rpm=a.rpm)
    if a.tool == "drill":
        t = tooling.drill(a.d, a.d * 3)
        cd = cutting.drilling(t, mat, machine)
    elif a.tool == "tap":
        t = tooling.tap(a.thread or f"M{_n(a.d)}", through=False)
        cd = cutting.tapping(t, mat, machine)
    elif a.tool == "reamer":
        t = tooling.reamer(a.d, "")
        cd = cutting.reaming(t, mat, machine)
    elif a.tool == "face_mill":
        t = tooling.face_mill()
        cd = cutting.face_milling(t, mat, machine, ap=a.ap or mat.face_mill["ap"], width=t.diameter)
    else:
        t = tooling.pick_end_mill(mat.group, a.d, min_d=a.d)
        if t is None:
            print(f"Нет фрезы Ø{_n(a.d)} в библиотеке", file=sys.stderr)
            return 2
        if a.z:
            t.flutes = a.z
        cd = cutting.milling(t, mat, machine, a.op, ap=a.ap, ae=a.ae)
    print(f"{mat.name} · {t.label()} · {machine.name}")
    print(f"S{cd.rpm} об/мин  F{_n(cd.feed)} мм/мин  Vc={_n(cd.vc)} м/мин"
          + (f"  fz={_n(cd.fz)}" if cd.fz else "") + (f"  f={_n(cd.f_rev)} мм/об" if cd.f_rev else "")
          + (f"  ap={_n(cd.ap)}" if cd.ap else "") + (f"  ae={_n(cd.ae)}" if cd.ae else "")
          + (f"  P≈{_n(cd.power_kw)} кВт" if cd.power_kw else ""))
    for lim in cd.limits:
        print(f"  ограничено: {lim}")
    return 0


def cmd_materials(_a) -> int:
    for m in all_materials().values():
        print(f"{m.name}: {m.hardness}; псевдонимы: {', '.join(m.aliases)}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="numcraft", description="NumCraft — помощник технолога-фрезеровщика (Haas VF-2)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("plan", help="техкарта по описанию / STEP / чертежу / JSON")
    pp.add_argument("text", nargs="*", help="описание детали на русском («-» — читать из stdin)")
    pp.add_argument("--step", help="STEP-модель (.step/.stp)")
    pp.add_argument("--drawing", help="чертёж (.pdf с текстом, .dxf, .txt)")
    pp.add_argument("--json", help="деталь в формате Part (JSON-файл или строка)")
    pp.add_argument("--material", help="материал: 6061, 7075, сталь 45, 1045")
    pp.add_argument("--name", help="наименование детали")
    pp.add_argument("--stock", type=_stock, help="заготовка, напр. 126x86x30")
    pp.add_argument("--gcode", action="store_true", help="добавить черновик УП")
    pp.add_argument("--dialect", choices=["fanuc", "haas"], default="fanuc")
    pp.add_argument("--rpm", type=int, help="макс. обороты шпинделя (опция 12000)")
    pp.add_argument("-o", "--out", help="сохранить техкарту .md")
    pp.add_argument("--json-out", help="сохранить техкарту .json")
    pp.add_argument("--nc", help="сохранить УП .nc")
    pp.add_argument("--brief", action="store_true", help="только таблицы, без параметров стратегий")
    pp.set_defaults(fn=cmd_plan)

    ps = sub.add_parser("step", help="анализ STEP")
    ps.add_argument("file")
    ps.set_defaults(fn=cmd_step)

    pd = sub.add_parser("drawing", help="обозначения с чертежа")
    pd.add_argument("file")
    pd.set_defaults(fn=cmd_drawing)

    pc = sub.add_parser("cut", help="режимы резания для одного инструмента")
    pc.add_argument("--material", required=True)
    pc.add_argument("--tool", default="end_mill", choices=["end_mill", "drill", "tap", "reamer", "face_mill"])
    pc.add_argument("--d", type=float, default=10)
    pc.add_argument("--z", type=int, help="число зубьев")
    pc.add_argument("--thread", help="резьба, напр. M8")
    pc.add_argument("--op", default="adaptive",
                    choices=["adaptive", "slot", "pocket", "finish_wall", "finish_floor", "contour", "bore"])
    pc.add_argument("--ap", type=float)
    pc.add_argument("--ae", type=float)
    pc.add_argument("--rpm", type=int)
    pc.set_defaults(fn=cmd_cut)

    pm = sub.add_parser("materials", help="поддерживаемые материалы")
    pm.set_defaults(fn=cmd_materials)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (UnknownMaterial, ValueError, FileNotFoundError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
