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
        w(f"<!--sk:s{s.number}-->")
        w("")
        w("| Оп. | Операция | Стратегия HSMWorks | Инструмент | S, об/мин | F, мм/мин | ap, мм | ae, мм | Vc, м/мин | Подача |")
        w("|---|---|---|---|---|---|---|---|---|---|")
        for op in s.operations:
            w(f"| {op.number} | {op.title} | {op.strategy}{' ' + op.cycle if op.cycle else ''} | "
              f"T{op.tool.number} — {op.tool.label()} | "
              f"{op.cutting.rpm} | {_feed(op)} | {_v(op.cutting.ap)} | {_v(op.cutting.ae)} | {_n(op.cutting.vc)} | "
              f"{_fz(op)} |")
        w("")
        if details:
            for op in s.operations:
                w(f"### Оп. {op.number}. {op.title} · T{op.tool.number} — {op.tool.label()}")
                w("")
                w(f"<!--sk:o{op.number}-->")
                w(f"- **Стратегия:** {op.strategy}")
                if op.selection:
                    w(f"- **Что выбрать в HSMWorks:** {op.selection}")
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
    w("| T / H / D | Инструмент | Артикул | Ø, мм | z | Lc, мм | L общ., мм | Вылет, мм | Материал | Операции |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    uses: Dict[int, List[str]] = {}
    for s in sheet.setups:
        for op in s.operations:
            uses.setdefault(op.tool.number, []).append(str(op.number))
    for t in sheet.tools:
        mat = t.tool_material + (f", {t.coating}" if t.coating else "")
        art = f"{t.article} ({'склад' if t.in_stock else 'под заказ'})" if t.article else "—"
        w(f"| T{t.number} / H{t.number} / D{t.number} | {t.label()} | {art} | {_n(t.diameter)} | {t.flutes} | "
          f"{_v(t.flute_length or None)} | {_v(t.overall_length or None)} | {_v(t.stickout or None)} | {mat} | "
          f"{', '.join(uses.get(t.number, []))} |")
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


_CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#666;--line:#ddd;--head:#f3f4f6;--hi:#fde8e8;--mid:#fff6db;--code:#f6f8fa;
--partfill:#e9edf2;--hl:#d9480f;--hlfill:rgba(217,72,15,.30);--datum:#1971c2;--partbg:#f7f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e8e8e8;--muted:#9aa;--line:#333;--head:#22252b;
--hi:#4a1f1f;--mid:#3f3519;--code:#1e2127;--partfill:#262b33;--hl:#ff8a4c;--hlfill:rgba(255,138,76,.32);
--datum:#5fa8ff;--partbg:#1b1e23}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
max-width:1760px;margin:0 auto;padding:16px}
h1{font-size:24px}h2{margin-top:32px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:18px 0 4px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:14px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}th{background:var(--head)}
tr.high td{background:var(--hi)}tr.mid td{background:var(--mid)}
pre{background:var(--code);padding:12px;overflow-x:auto;font-size:13px}
blockquote{color:var(--muted);border-left:3px solid var(--line);margin:16px 0;padding-left:12px}
details{margin:4px 0}summary{cursor:pointer;color:var(--muted)}
details[open]{border-left:3px solid var(--hl);padding:0 0 4px 10px}
.tools button{font:inherit;padding:4px 10px;border:1px solid var(--line);background:var(--head);color:var(--fg);
border-radius:6px;cursor:pointer}
figure.skf{margin:8px 0}figcaption{color:var(--muted);font-size:13px}.sk-note{color:var(--muted)}
svg.sk{display:block;width:100%;max-width:520px;height:auto}
.sk .stock{fill:none;stroke:var(--muted);stroke-width:calc(var(--sw)*1.2)}
.sk .part{fill:var(--partfill);stroke:var(--fg);stroke-width:calc(var(--sw)*1.6)}
.sk .feat{fill:var(--bg);stroke:var(--muted);stroke-width:var(--sw)}
.sk .ref{fill:none;stroke:var(--muted);stroke-width:var(--sw)}
.sk .hl{fill:var(--hlfill);stroke:var(--hl);stroke-width:calc(var(--sw)*2)}
.sk .hll{fill:none;stroke:var(--hl);stroke-width:calc(var(--sw)*4)}
.sk .datum{stroke:var(--datum);stroke-width:calc(var(--sw)*2.5)}
.sk text{fill:var(--muted);font-family:system-ui,sans-serif}.sk .num{fill:var(--hl);font-weight:700}
.sk .datum-t{fill:var(--datum);font-weight:600}
"""


def to_html(md: str, sheet: TechSheet) -> str:
    """Markdown техкарты → HTML; маркеры <!--sk:…--> заменяются схемами (SVG) установов и операций."""
    import html
    import re

    from numcraft.sketch import setup_svg
    from numcraft.viewer3d import CSS as V3D_CSS, viewer_html

    title = f"Техкарта: {sheet.part.name}"
    sketches = {}
    for s in sheet.setups:
        sketches[f"s{s.number}"] = setup_svg(sheet, s)
        for op in s.operations:
            sketches[f"o{op.number}"] = setup_svg(sheet, s, op)

    def inline(t: str) -> str:
        t = html.escape(t)
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)

    out = [f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
           f"<style>{_CSS}{V3D_CSS}</style></head><body><div class='layout'><main>",
           "<p class='tools'><button onclick=\"document.querySelectorAll('details').forEach(d=>d.open=true)\">"
           "Развернуть все операции</button> <button onclick=\"document.querySelectorAll('details')"
           ".forEach(d=>d.open=false)\">Свернуть</button></p>"]
    lines = md.splitlines()
    i = 0
    in_details = False
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"<!--sk:(\w+)-->$", ln.strip())
        if m:
            out.append(sketches.get(m.group(1), ""))
            if m.group(1).startswith("o") and sheet.model3d:
                out.append(f"<button class='btn3d' onclick='nc3dShow({m.group(1)[1:]})'>Показать в 3D</button>")
            i += 1
            continue
        if ln.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr>")
            for r in rows[2:]:
                cls = " class='high'" if r and r[0] == "ВЫСОКИЙ" else " class='mid'" if r and r[0] == "средний" else ""
                out.append(f"<tr{cls}>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</table>")
            continue
        if ln.startswith("- "):
            out.append("<ul>")
            while i < len(lines) and lines[i].startswith("- "):
                out.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("</ul>")
            continue
        if ln.startswith("### "):
            # подробности операции сворачиваем, чтобы таблицы установа читались целиком
            if in_details:
                out.append("</details>")
            out.append(f"<details><summary>{inline(ln[4:])}</summary>")
            in_details = True
        elif ln.startswith("## ") or ln.startswith("# "):
            if in_details:
                out.append("</details>")
                in_details = False
            lvl = 1 if ln.startswith("# ") else 2
            out.append(f"<h{lvl}>{inline(ln[lvl + 1:])}</h{lvl}>")
        elif ln.startswith("> "):
            out.append(f"<blockquote>{inline(ln[2:])}</blockquote>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    if in_details:
        out.append("</details>")
    out.append("</main>")
    if sheet.model3d:
        out.append("<aside>" + viewer_html(sheet.model3d) + "</aside>")
    out.append("</div></body></html>")
    return "\n".join(out)
