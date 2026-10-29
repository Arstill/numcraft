"""
Чат-агент «Технолог» (Coze / OpenAI-совместимая модель).

Агент уточняет недостающие данные, вызывает детерминированные инструменты numcraft и пересказывает
результат. Режимы резания и глубины агент не придумывает — только из инструментов.
"""
import json
from pathlib import Path
from typing import Annotated, List

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AnyMessage
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages

from numcraft import cutting
from numcraft.knowledge import tooling
from numcraft.knowledge.machine import load_machine
from numcraft.knowledge.materials import resolve_material
from numcraft.llm import CONFIG, make_llm
from numcraft.pipeline import InputError, Inputs, run
from numcraft.techsheet import to_markdown

# Последние 20 обменов
MAX_MESSAGES = 40


def _windowed_messages(old, new):
    return add_messages(old, new)[-MAX_MESSAGES:]


class AgentState(MessagesState):
    messages: Annotated[List[AnyMessage], _windowed_messages]


@tool
def plan_part(description: str = "", step_path: str = "", drawing_path: str = "", material: str = "",
              stock: str = "", gcode: bool = False, dialect: str = "fanuc") -> str:
    """Построить техкарту под Haas VF-2: установы, инструмент, режимы, стратегии HSMWorks, риски.

    Args:
        description: описание детали на русском (габарит Д×Ш×В, материал, карманы, отверстия, резьбы, фаски)
        step_path: путь к STEP-модели (если есть)
        drawing_path: путь к чертежу PDF/DXF (если есть)
        material: 6061, 7075, сталь 45 или 1045 (если не указан в описании)
        stock: заготовка «126x86x30» (если известна)
        gcode: добавить черновик УП FANUC
        dialect: fanuc или haas
    """
    st = [float(x) for x in stock.lower().replace("х", "x").split("x")] if stock else None
    try:
        res = run(Inputs(text=description or None, step_path=step_path or None, drawing_path=drawing_path or None,
                         material=material or None, stock=st), gcode=gcode, dialect=dialect)
    except InputError as e:
        return "НЕ ХВАТАЕТ ДАННЫХ — спроси у пользователя: " + "; ".join(e.missing)
    md = to_markdown(res.sheet)
    if res.step_summary:
        md += "\n## Анализ STEP\n```\n" + res.step_summary + "\n```\n"
    return md


@tool
def analyze_step(step_path: str) -> str:
    """Разобрать STEP: габарит, отверстия, карманы, радиусы, направления обработки."""
    from numcraft.parsers.step import analyze_step_file, summary_ru

    return summary_ru(analyze_step_file(step_path))


@tool
def analyze_drawing(drawing_path: str) -> str:
    """Извлечь обозначения с чертежа (PDF/DXF): материал, квалитеты, резьбы, Ra, общие допуски."""
    from numcraft.parsers.drawing import analyze_drawing as _an

    info = _an(drawing_path)
    return json.dumps({"material": info.material, "general_tolerance": info.general_tolerance, "fits": info.fits,
                       "threads": info.threads, "ra": info.ra_values, "warnings": info.warnings},
                      ensure_ascii=False)


@tool
def cutting_data(material: str, tool_kind: str = "end_mill", diameter: float = 10.0, operation: str = "adaptive",
                 thread: str = "") -> str:
    """Режимы резания для одного инструмента на Haas VF-2.

    Args:
        material: 6061, 7075, сталь 45, 1045
        tool_kind: end_mill | drill | tap | reamer
        diameter: диаметр, мм
        operation: для фрез — adaptive | slot | pocket | finish_wall | finish_floor | contour | bore
        thread: для метчика — «M8»
    """
    mat, machine = resolve_material(material), load_machine()
    if tool_kind == "drill":
        t = tooling.drill(diameter, diameter * 3, mat.group)
        cd = cutting.drilling(t, mat, machine)
    elif tool_kind == "tap":
        t = tooling.tap(thread or f"M{int(diameter)}", through=False)
        cd = cutting.tapping(t, mat, machine)
    elif tool_kind == "reamer":
        t = tooling.reamer(diameter, "", group=mat.group)
        cd = cutting.reaming(t, mat, machine)
    else:
        t = tooling.pick_end_mill(mat.group, diameter, min_d=diameter)
        if t is None:
            return f"Нет фрезы Ø{diameter} в библиотеке"
        cd = cutting.milling(t, mat, machine, operation)
    return f"{mat.name}, {t.label()}: " + cd.model_dump_json(exclude_none=True)


def build_agent(ctx=None):
    cfg = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
    try:
        from storage.memory.memory_saver import get_memory_saver

        checkpointer = get_memory_saver()
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
    return create_agent(
        model=make_llm(ctx, streaming=True),
        system_prompt=cfg.get("sp"),
        tools=[plan_part, analyze_step, analyze_drawing, cutting_data],
        checkpointer=checkpointer,
        state_schema=AgentState,
    )
