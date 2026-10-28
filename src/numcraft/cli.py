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


FILE_KINDS = {".step": "step", ".stp": "step", ".pdf": "drawing", ".dxf": "drawing", ".json": "json"}


def _route_files(a) -> list:
    """Файлы в позиционных аргументах (перетаскивание на numcraft.bat) раскладываем по типу."""
    words, files = [], []
    for w in a.text or []:
        kind = FILE_KINDS.get(Path(w).suffix.lower())
        if kind and Path(w).is_file():
            setattr(a, kind, getattr(a, kind) or w)
            files.append(Path(w))
        else:
            words.append(w)
    a.text = words
    return files


def _ask_material() -> str | None:
    if not sys.stdin.isatty():
        return None
    try:
        return input("Материал не найден в файлах. Введите (6061 / 7075 / 45 / 1045): ").strip() or None
    except EOFError:
        return None


def _ask_stock(part, proposed):
    """Ручной ввод заготовки в консоли; Enter — оставить предложенную."""
    from numcraft.models import Box

    if not sys.stdin.isatty():
        return None
    print(f"\nДеталь «{part.name}»: {part.size.fmt()} (X × Y × Z — длина × ширина × высота).")
    while True:
        try:
            line = input(f"Заготовка X×Y×Z, мм (Enter — предложенная {proposed.fmt()}): ").strip()
        except EOFError:
            return None
        if not line:
            return None
        try:
            x, y, z = _stock(line)
        except argparse.ArgumentTypeError:
            print("  Введите три числа через «x», например 130x90x30.")
            continue
        if x < part.size.x - 0.01 or y < part.size.y - 0.01 or z < part.size.z - 0.01:
            print(f"  Заготовка меньше детали ({part.size.fmt()}). Если деталь в заготовке развёрнута — "
                  "укажите размеры в порядке X × Y × Z детали.")
            continue
        return Box(x=x, y=y, z=z)


def cmd_plan(a) -> int:
    from numcraft.pipeline import InputError, Inputs, run
    from numcraft.techsheet import to_html, to_json, to_markdown

    files = _route_files(a)
    text = " ".join(a.text) if a.text else None
    if text == "-":
        text = sys.stdin.read()
    material = a.material
    for _ in range(2):
        try:
            res = run(Inputs(text=text, step_path=a.step, drawing_path=a.drawing, part_json=a.json,
                             material=material, name=a.name, stock=a.stock),
                      gcode=a.gcode, dialect=a.dialect, max_rpm=a.rpm,
                      ask_stock=_ask_stock if a.ask_stock and not a.stock else None)
            break
        except InputError as e:
            if not material and any("материал" in m.lower() for m in e.missing) and (material := _ask_material()):
                continue
            print("Не хватает данных для техкарты:", file=sys.stderr)
            for m in e.missing:
                print(f"  • {m}", file=sys.stderr)
            if a.drawing and not a.step and not text:
                print("  • по одному PDF геометрию не получить — добавьте STEP-модель детали", file=sys.stderr)
            return 2
    md = to_markdown(res.sheet, details=not a.brief)
    if res.step_summary and not a.brief:
        md = md.replace("\n## ", "\n## Анализ STEP\n\n```\n" + res.step_summary + "\n```\n\n## ", 1)
    out, html_out, nc = a.out, a.html, a.nc
    if files and not (out or html_out):
        # результат — рядом с моделью: корпус.step → корпус_техкарта.html / .md / .nc
        base = files[0].with_name(files[0].stem + "_техкарта")
        out, html_out = str(base) + ".md", str(base) + ".html"
        if res.sheet.gcode and not nc:
            nc = str(files[0].with_suffix(".nc"))
    if out:
        Path(out).write_text(md, encoding="utf-8")
        print(f"Техкарта: {out}")
    if html_out:
        Path(html_out).write_text(to_html(md, res.sheet), encoding="utf-8")
        print(f"Техкарта (браузер): {html_out}")
    if not (out or html_out):
        print(md)
    if a.json_out:
        Path(a.json_out).write_text(to_json(res.sheet), encoding="utf-8")
        print(f"JSON: {a.json_out}")
    if nc and res.sheet.gcode:
        Path(nc).write_text(res.sheet.gcode, encoding="utf-8")
        print(f"УП: {nc}")
    if a.open and (html_out or out):
        _open(html_out or out)
    return 0


def _open(path: str) -> None:
    import os
    import webbrowser

    if hasattr(os, "startfile"):
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        webbrowser.open(Path(path).resolve().as_uri())


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


def cmd_catalog(a) -> int:
    from numcraft.catalogs import zcc

    if a.what == "main":
        from numcraft.catalogs.zcc_main import build_yaml, parse

        text = Path(a.file).read_text(encoding="utf-8")
        out = a.out or str(Path(__file__).parent / "knowledge" / "catalogs" / "zcc_tools.yaml")
        Path(out).write_text(build_yaml(text), encoding="utf-8")
        print(f"Инструментов ZCC: {len(parse(text))} → {out}")
        return 0
    if a.what == "text":
        out = a.out or str(Path(a.file).with_suffix(".txt"))
        print(f"Выгружаю текст из {a.file} … (большой каталог — несколько минут)")
        n = zcc.dump_text(a.file, out, a.pages)
        size = Path(out).stat().st_size / 1e6
        print(f"Готово: {n} стр. → {out} ({size:.1f} МБ). Этот файл можно отправить для подключения каталога.")
        return 0
    import yaml

    rows = zcc.parse_taps_pdf(a.file)
    if not rows:
        print("В файле не найдено таблиц метчиков ZCC.", file=sys.stderr)
        return 2
    out = a.out or str(Path(__file__).parent / "knowledge" / "catalogs" / "zcc_taps.yaml")
    Path(out).write_text(yaml.safe_dump({"catalog": "ZCC-CT HSS tools", "taps": rows}, allow_unicode=True,
                                        sort_keys=False, width=120), encoding="utf-8")
    print(f"Метчиков: {len(rows)} → {out}")
    return 0


def _split_dropped(line: str) -> list:
    """Строка после перетаскивания файлов в окно: пути в кавычках или без, через пробел."""
    import shlex

    parts = shlex.split(line, posix=False)
    return [p.strip('"') for p in parts if p.strip('"')]


def cmd_drop(a) -> int:
    """Режим для numcraft.bat: файлы из аргументов или перетаскиванием в окно, техкарта открывается сама."""
    def run_files(files: list) -> int:
        return main(["plan", *files, "--ask-stock", "--open"])

    if a.files:
        return run_files(a.files)
    while True:
        print()
        print("=" * 64)
        print(" Перетащите в это окно STEP-модель и/или PDF чертежа детали,")
        print(" затем нажмите Enter. Пустой Enter — выход.")
        print("=" * 64)
        try:
            line = input("Файлы: ").strip()
        except EOFError:
            return 0
        if not line:
            return 0
        run_files(_split_dropped(line))


def cmd_catalog_drop(a) -> int:
    """Режим для catalog_text.bat: PDF каталога из аргумента или перетаскиванием в окно."""
    path = a.file
    if not path:
        try:
            path = " ".join(_split_dropped(input("Перетащите в окно PDF каталога ZCC и нажмите Enter: ")))
        except EOFError:
            return 0
    if not path:
        return 0
    return main(["catalog", "text", path, "-o", str(Path(path).with_suffix(".txt"))])


def cmd_materials(_a) -> int:
    for m in all_materials().values():
        print(f"{m.name}: {m.hardness}; псевдонимы: {', '.join(m.aliases)}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="numcraft", description="NumCraft — помощник технолога-фрезеровщика (Haas VF-2)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("plan", help="техкарта по описанию / STEP / чертежу / JSON")
    pp.add_argument("text", nargs="*", help="файлы STEP/PDF/DXF/JSON и/или описание детали («-» — из stdin)")
    pp.add_argument("--step", help="STEP-модель (.step/.stp)")
    pp.add_argument("--drawing", help="чертёж (.pdf с текстом, .dxf, .txt)")
    pp.add_argument("--json", help="деталь в формате Part (JSON-файл или строка)")
    pp.add_argument("--material", help="материал: 6061, 7075, сталь 45, 1045")
    pp.add_argument("--name", help="наименование детали")
    pp.add_argument("--stock", type=_stock, help="заготовка, напр. 126x86x30")
    pp.add_argument("--gcode", action="store_true", help="добавить черновик УП")
    pp.add_argument("--ask-stock", action="store_true", help="спросить размеры заготовки в консоли")
    pp.add_argument("--dialect", choices=["fanuc", "haas"], default="fanuc")
    pp.add_argument("--rpm", type=int, help="макс. обороты шпинделя (опция 12000)")
    pp.add_argument("-o", "--out", help="сохранить техкарту .md")
    pp.add_argument("--html", help="сохранить техкарту .html (для браузера)")
    pp.add_argument("--open", action="store_true", help="открыть техкарту после расчёта")
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

    pk = sub.add_parser("catalog", help="каталог ZCC: taps — метчики из PDF, text — текст из PDF, "
                                         "main — фрезы/свёрла из текста основного каталога")
    pk.add_argument("what", choices=["taps", "text", "main"])
    pk.add_argument("file", help="PDF каталога (для main — .txt, выгруженный командой text)")
    pk.add_argument("-o", "--out", help="куда сохранить")
    pk.add_argument("--pages", help="страницы, напр. 120-380 (для text)")
    pk.set_defaults(fn=cmd_catalog)

    pdrop = sub.add_parser("drop", help="режим перетаскивания файлов (numcraft.bat)")
    pdrop.add_argument("files", nargs="*")
    pdrop.set_defaults(fn=cmd_drop)

    pcd = sub.add_parser("catalog-drop", help="выгрузка текста каталога перетаскиванием (catalog_text.bat)")
    pcd.add_argument("file", nargs="?")
    pcd.set_defaults(fn=cmd_catalog_drop)

    pm = sub.add_parser("materials", help="поддерживаемые материалы")
    pm.set_defaults(fn=cmd_materials)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (UnknownMaterial, ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
