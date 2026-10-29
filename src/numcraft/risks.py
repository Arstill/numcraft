"""Правила рисков: крепление, жёсткость, вылет, глубокие отверстия, ограничения станка."""
from __future__ import annotations

from typing import List

from numcraft.knowledge.machine import Machine
from numcraft.knowledge.materials import Material
from numcraft.models import (
    ContourFeature, HoleFeature, PocketFeature, Risk, SlotFeature, SurfaceFeature, TechSheet, ThreadFeature, _n,
)

HOLDER_GAUGE_MM = 60  # вылет патрона CT40 от торца шпинделя (типовой)
VISE_STACK_MM = 160  # высота тисков + параллелей


def assess(sheet: TechSheet, mat: Material, machine: Machine) -> List[Risk]:
    risks: List[Risk] = []
    part, stock = sheet.part, sheet.stock
    ps = part.size

    def add(level, topic, msg, action):
        risks.append(Risk(level=level, topic=topic, message=msg, action=action))

    # --- станок
    tr = machine.travel_mm
    if stock.x > tr["x"] or stock.y > tr["y"]:
        add("высокий", "Ходы станка", f"Заготовка {stock.fmt()} больше ходов {machine.name} X{tr['x']}/Y{tr['y']}.",
            "Разбить обработку на перестановки или выбрать другой станок.")
    elif stock.y > tr["y"] - 40:
        add("средний", "Ходы станка", f"По Y запас хода мал ({_n(tr['y'] - stock.y)} мм) с учётом радиуса фрезы.",
            "Развернуть деталь длинной стороной вдоль X.")
    longest = max((t.overall_length for t in sheet.tools), default=0)
    if stock.z + longest + HOLDER_GAUGE_MM + VISE_STACK_MM > machine.spindle_nose_to_table_mm["max"]:
        add("средний", "Высота по Z", "Длинный инструмент + высокая заготовка в тисках близки к пределу по Z.",
            "Проверить по Z до смены инструмента: заготовка + тиски + самый длинный инструмент.")
    if len(sheet.tools) > machine.tool_changer["pockets"]:
        add("высокий", "Магазин", f"Инструментов {len(sheet.tools)} > гнёзд магазина {machine.tool_changer['pockets']}.",
            "Объединить инструмент (одна фреза на черновую и чистовую) или менять вручную между установами.")

    # --- крепление
    if max(stock.x, stock.y) > 2.2 * machine.vise.jaw_width_mm:
        add("средний", "Крепление", f"Длинная заготовка ({_n(max(stock.x, stock.y))} мм) при губках "
            f"{_n(machine.vise.jaw_width_mm)} мм — свес и вибрации на концах.",
            "Двое тисков в линию или прихваты; концы обрабатывать с уменьшенным ae.")
    if ps.z < 6 and ps.x * ps.y > 4000:
        add("средний", "Тонкая плита", f"Толщина {_n(ps.z)} мм при площади {_n(ps.x)}×{_n(ps.y)} — прогиб от зажима "
            "и коробление после снятия.", "Вакуумный стол или прихваты по периметру; умеренное усилие тисков; "
            "черновая с обеих сторон, затем чистовая.")
    extra = stock.z - ps.z
    if 0.02 < extra - 1.0 < 4.3:
        add("средний", "Захват", f"Снизу под захват остаётся {_n(round(extra - 1, 1))} мм — меньше рекомендуемых "
            f"{_n(machine.vise.recommended_grip_mm)} мм + 1.3 мм зазора под контур.",
            "Взять заготовку толще или обработать контур в два пояса (заложено в плане).")

    # --- материал
    if mat.key == "al7075" and max(ps.x, ps.y) / max(ps.z, 1) > 12:
        add("средний", "Коробление 7075", "Плоская деталь из 7075-T6: возможен увод от остаточных напряжений.",
            "Черновая с припуском 0.5–1 мм с обеих сторон, отпустить тиски, затем чистовая.")

    # --- отверстие на стенке кармана/паза (окружность пересекает границу)
    from numcraft.sketch import _feature_box

    for h in part.features:
        if not isinstance(h, (HoleFeature, ThreadFeature)) or not h.positions:
            continue
        r = h.diameter / 2 if isinstance(h, HoleFeature) else _thread_d(h.size) / 2
        for pk in part.features:
            box = _feature_box(pk)
            if box is None or pk.side != h.side:
                continue
            for x, y in h.positions:
                over_x = box[0] - r < x < box[2] + r and box[1] - r < y < box[3] + r
                inside = box[0] + r <= x <= box[2] - r and box[1] + r <= y <= box[3] - r
                if over_x and not inside:
                    add("высокий", "Геометрия", f"{h.id}: отверстие ({_n(x)}; {_n(y)}) пересекает стенку {pk.id}.",
                        "Проверить координаты по чертежу: сверло уйдёт в стенку, возможна поломка.")
                    break

    # --- геометрия
    for f in part.features:
        if isinstance(f, PocketFeature):
            floor = ps.z - f.depth
            if not f.through and floor <= 0:
                add("высокий", "Геометрия", f"{f.id}: глубина кармана {_n(f.depth)} мм ≥ толщины {_n(ps.z)} мм.",
                    "Уточнить глубину или указать «сквозной».")
            elif not f.through and floor < 1.5:
                add("высокий" if floor < 0.8 else "средний", "Тонкое дно",
                    f"{f.id}: дно кармана {_n(round(floor, 2))} мм.",
                    "Дно чистить последним, с малым ap; поддержка снизу (параллели под дном).")
            if f.center:
                cx, cy = f.center
                wall = min(cx - f.length / 2, ps.x - cx - f.length / 2, cy - f.width / 2, ps.y - cy - f.width / 2)
                if wall < 0:
                    add("высокий", "Геометрия", f"{f.id}: карман выходит за габарит детали.", "Проверить размеры.")
                elif wall < 1.0 or f.depth / max(wall, 0.01) > 10:
                    add("высокий", "Тонкая стенка", f"{f.id}: стенка {_n(round(wall, 2))} мм при высоте {_n(f.depth)} мм.",
                        "Чистовую стенки ступенями сверху вниз (Multiple depths), ae ≤ 0.1 мм, свежая фреза; "
                        "наружный контур чистить до кармана.")
                elif f.depth / wall > 6:
                    add("средний", "Стенка", f"{f.id}: стенка {_n(round(wall, 2))} мм, отношение h/t = "
                        f"{_n(round(f.depth / wall, 1))}.", "Чистовую стенки в 2 ступени по Z, ae 0.1–0.15 мм.")
            if f.corner_radius and f.corner_radius < 1.5:
                add("средний", "Малый радиус", f"{f.id}: R{_n(f.corner_radius)} в углах — нужна фреза Ø≤{_n(2 * f.corner_radius - 0.5)}.",
                    "Уточнить у конструктора, допустим ли R больше. Малая фреза — малая глубина за проход.")
        if isinstance(f, ThreadFeature) and mat.group == "steel":
            from numcraft.knowledge.tooling import parse_thread
            d, _ = parse_thread(f.size)
            if d <= 5:
                add("средний", "Метчик в стали", f"{f.id}: {f.size} в стали — риск поломки метчика.",
                    "Метчик HSS-E-PM/TiCN, точное сверло под резьбу, масло; при глухих — сверлить глубже, "
                    "рассмотреть резьбонакатку (раскатник) или резьбофрезу.")
        if isinstance(f, (HoleFeature, ThreadFeature)) and not f.through:
            depth = f.depth or 0
            if depth and depth > ps.z - 1:
                add("высокий", "Глухое отверстие", f"{f.id}: глубина {_n(depth)} мм при толщине {_n(ps.z)} мм — "
                    "вершина сверла выйдет насквозь или стенка дна < 1 мм.", "Уточнить глубину или сделать сквозным.")
        if isinstance(f, HoleFeature) and f.fit and f.fit.upper() in ("H6", "H7") and f.diameter > 20:
            add("средний", "Точное отверстие", f"{f.id}: Ø{_n(f.diameter)}{f.fit.upper()} — спиральной расточкой "
                "на VF-2 держать сложно.", "Расточная головка (Ø{0}) или калибр-пробка с подгонкой износа D."
                .format(_n(f.diameter)))
        if isinstance(f, ContourFeature) and f.tolerance and f.tolerance < 0.015:
            add("высокий", "Допуск", f"Контур с допуском ±{_n(f.tolerance)} мм — на пределе VF-2 без термостабилизации.",
                "Прогрев шпинделя 15–20 мин, отдельная чистовая фреза, замер на станке, подгонка износом D.")
        if isinstance(f, SurfaceFeature):
            add("низкий", "3D", f"{f.id}: 3D-поверхность — траектории строятся в HSMWorks, обязательна симуляция.",
                "Проверить зарезы держателем (Holder), задать Tolerance ≤ 0.01 мм, Smoothing вкл.")
        if isinstance(f, SlotFeature) and f.width < 3:
            add("средний", "Узкий паз", f"{f.id}: паз {_n(f.width)} мм — хрупкая фреза малого диаметра.",
                "ap ≤ 0.3D за проход, обязательна СОЖ/обдув для выноса стружки.")

    # --- операции (одинаковые замечания по одному инструменту объединяются)
    agg: dict = {}

    def add_op(op, level, topic, msg, action):
        k = (level, topic, msg, action)
        agg.setdefault(k, []).append(op.number)

    for s in sheet.setups:
        for op in s.operations:
            t = op.tool
            depth = (op.z_start or 0) - (op.z_depth or 0)
            ld = depth / t.diameter if t.diameter else 0
            if t.kind == "end_mill" and t.reach and t.flute_length < depth <= t.reach + 0.01:
                add_op(op, "средний", "Фреза с шейкой", f"{t.article or t.label()}: Lc {_n(t.flute_length)} мм, "
                       f"шейка {_n(t.reach)} мм на глубину {_n(round(depth, 2))} мм",
                       "Стенки — в несколько проходов по Z (Multiple depths, шаг ≤ Lc), ae и fz −20…30 %.")
            elif t.kind == "end_mill" and t.flute_length and depth > t.flute_length + 0.01 and op.strategy != "Bore (спиральная расточка)":
                add_op(op, "высокий", "Длина режущей части", f"глубина {_n(round(depth, 2))} мм > Lc {_n(t.flute_length)} "
                       f"фрезы Ø{_n(t.diameter)}", "Хвостовик заденет стенку: фреза с удлинённой режущей частью "
                       "или шейкой (Neck), либо обработка в два пояса с переворотом.")
            if t.kind == "tap" and t.reach and depth > t.reach + 0.01:
                add_op(op, "высокий", "Длина метчика", f"глубина {_n(round(depth, 2))} мм от верха > рабочей длины "
                       f"{t.article or 'метчика'} {_n(t.reach)} мм", "Метчик с хвостовиком DIN 376/374 "
                       "(хвостовик проходит в отверстие) или удлинённый; уточнить глубину резьбы.")
            if t.overall_length and t.kind != "face_mill":
                grip = max(20.0, 3 * (t.shank_d or t.diameter))
                if depth + 5 > t.overall_length - grip:
                    add_op(op, "высокий", "Длина инструмента", f"{t.article or t.label()}: нужно ≥ "
                           f"{_n(round(depth + 5, 1))} мм вылета (глубина + 5 мм над деталью), а при зажиме ≥ "
                           f"{_n(grip)} мм доступно {_n(round(t.overall_length - grip, 1))} мм",
                           "Взять удлинённое исполнение (большая общая длина / шейка) по каталогу ZCC.")
            if t.kind == "end_mill" and ld > 4:
                add_op(op, "высокий", "Вылет", f"глубина {_n(round(depth, 2))} мм фрезой Ø{_n(t.diameter)} "
                       f"(L/D = {_n(round(ld, 1))})", "Удлинённая фреза с шейкой, ae и fz −30 %, термо/гидропатрон; "
                       "проверить, нельзя ли увеличить радиус в углах и взять фрезу больше.")
            elif t.kind == "end_mill" and ld > 3:
                add_op(op, "средний", "Вылет", f"L/D = {_n(round(ld, 1))} фрезой Ø{_n(t.diameter)}",
                       "Минимальный вылет, термопатрон/цанга ER с биением ≤ 0.01.")
            if t.kind == "drill" and "(СОЖ через инструмент)" in t.description:
                add_op(op, "высокий", "СОЖ через инструмент", f"{t.article}: сверло с внутренним подводом СОЖ, "
                       f"а на VF-2 нет TSC", "Заказать опцию TSC либо сверлить ступенчато: пилотное сверло 3xD + "
                       "G83 с малым Q, обильный полив.")
            if t.kind == "drill" and t.reach and depth > t.reach + 0.01:
                add_op(op, "высокий", "Длина сверла", f"{t.article}: глубина {_n(round(depth, 2))} мм > рабочей "
                       f"длины {_n(t.reach)} мм", "Сверло большей длины (8xD и выше) или сверление с двух сторон.")
            walls = [f for f in part.features if f.id in op.feature_ids and getattr(f, "walls", 1) > 1]
            if t.kind == "drill" and walls and ld > 5:
                add_op(op, "средний", "Сверление через стенки", f"Ø{_n(t.diameter)} на {_n(round(depth, 2))} мм через "
                       f"{walls[0].walls} стенки с пустотой", "Удлинённое сверло, G83; на входе во вторую стенку "
                       "подачу −50 % (увод). Альтернатива — короткое сверло с двух сторон (+1 установ).")
            elif t.kind == "drill" and ld > 8:
                add_op(op, "высокий", "Глубокое сверление", f"Ø{_n(t.diameter)} на {_n(round(depth, 2))} мм "
                       f"({_n(round(ld, 1))}xD)", "Сверло с внутренним подводом (нужен TSC) или пилотное "
                       "отверстие 2xD + длинное сверло; G83 с малым Q.")
            elif t.kind == "drill" and ld > 5 and op.cycle != "G83":
                add_op(op, "средний", "Сверление", f"{_n(round(ld, 1))}xD без полного вывода", "Использовать G83.")
            for lim in op.cutting.limits:
                if lim.startswith("мощность"):
                    add_op(op, "средний", "Мощность", lim, "Проверить нагрузку шпинделя на стойке (≤ 80 %).")
            if t.kind == "end_mill" and mat.is_aluminum and t.diameter <= 4 and op.cutting.rpm >= machine.spindle.max_rpm:
                add_op(op, "низкий", "Обороты", f"Ø{_n(t.diameter)} на {op.cutting.rpm} об/мин — Vc ниже оптимума "
                       f"({_n(op.cutting.vc)} м/мин)", "Держать fz по таблице, снижать ap; при наличии — шпиндель 12k.")
    for (level, topic, msg, action), nums in agg.items():
        label = "Оп. " + ", ".join(str(n) for n in nums)
        add(level, topic, f"{label}: {msg}.", action)

    if sheet.questions:
        add("средний", "Исходные данные", f"Есть {len(sheet.questions)} допущений по неполным данным.",
            "Проверить раздел «Вопросы к чертежу».")

    order = {"высокий": 0, "средний": 1, "низкий": 2}
    uniq = {}
    for r in risks:
        uniq.setdefault((r.topic, r.message), r)
    return sorted(uniq.values(), key=lambda r: order[r.level])


def _thread_d(size: str) -> float:
    from numcraft.knowledge.tooling import parse_thread

    return parse_thread(size)[0]
