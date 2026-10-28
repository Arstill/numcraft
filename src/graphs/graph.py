"""
Граф LangGraph: деталь → техкарта.

  intake ──► plan ──► review ──► render
     │         ▲         (LLM, опц.)
     └─► llm_extract (если детерминированный разбор не справился и use_llm)

Все числа считает пакет numcraft (planner/cutting); LLM только извлекает данные и комментирует.
"""
import logging
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from graphs.state import AssistantState, GraphInput, GraphOutput
from numcraft.gcode import generate
from numcraft.knowledge.machine import load_machine
from numcraft.models import Part, TechSheet
from numcraft.pipeline import InputError, Inputs, build_part
from numcraft.planner import plan_part
from numcraft.techsheet import to_markdown

logger = logging.getLogger(__name__)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def intake_node(state: AssistantState) -> Dict[str, Any]:
    drawing = state.get("drawing_path")
    image = drawing if drawing and Path(drawing).suffix.lower() in IMAGE_EXT else None
    inp = Inputs(text=state.get("text"), step_path=state.get("step_path"),
                 drawing_path=None if image else drawing, part_json=state.get("part_json"),
                 material=state.get("material"), name=state.get("name"))
    try:
        part, notes, step_summary = build_part(inp)
    except InputError as e:
        return {"missing": e.missing, "part": None}
    return {"part": part.model_dump(), "notes": notes, "step_summary": step_summary, "missing": []}


def route_after_intake(state: AssistantState) -> str:
    if state.get("part"):
        return "plan"
    if state.get("use_llm"):
        return "llm_extract"
    return "render"


def llm_extract_node(state: AssistantState) -> Dict[str, Any]:
    from numcraft import llm

    drawing = state.get("drawing_path")
    image = drawing if drawing and Path(drawing).suffix.lower() in IMAGE_EXT else None
    try:
        part = llm.extract_part(llm.make_llm(), text=state.get("text"), image_path=image)
    except Exception as e:  # сеть, ключ, невалидная схема
        logger.exception("LLM extract failed")
        return {"error": f"LLM не смог разобрать деталь: {e}"}
    if state.get("material"):
        part.material = state["material"]
    return {"part": part.model_dump(), "notes": ["Деталь извлечена LLM — проверьте размеры по чертежу."],
            "missing": []}


def plan_node(state: AssistantState) -> Dict[str, Any]:
    if not state.get("part"):
        return {}
    part = Part.model_validate(state["part"])
    try:
        sheet = plan_part(part, load_machine(max_rpm=state.get("max_rpm")))
    except ValueError as e:
        return {"error": str(e)}
    sheet.assumptions = list(state.get("notes") or []) + sheet.assumptions
    if state.get("gcode"):
        sheet.gcode = generate(sheet, dialect=state.get("dialect") or "fanuc")
    return {"techsheet": sheet.model_dump(), "gcode": sheet.gcode, "questions": sheet.questions,
            "risks": [r.model_dump() for r in sheet.risks]}


def review_node(state: AssistantState) -> Dict[str, Any]:
    if not (state.get("use_llm") and state.get("techsheet")):
        return {}
    from numcraft import llm

    try:
        return {"review": llm.review(llm.make_llm(), TechSheet.model_validate(state["techsheet"]))}
    except Exception as e:
        logger.warning("LLM review skipped: %s", e)
        return {}


def render_node(state: AssistantState) -> Dict[str, Any]:
    if state.get("techsheet"):
        md = to_markdown(TechSheet.model_validate(state["techsheet"]))
        if state.get("step_summary"):
            md += "\n## Анализ STEP\n\n```\n" + state["step_summary"] + "\n```\n"
        if state.get("review"):
            md += "\n## Комментарий технолога (LLM)\n\n" + state["review"] + "\n"
        return {"techsheet_md": md}
    if state.get("missing"):
        msg = "Не хватает данных для техкарты:\n" + "\n".join(f"- {m}" for m in state["missing"])
        return {"techsheet_md": msg, "questions": state["missing"], "error": state.get("error") or msg}
    return {"techsheet_md": state.get("error") or "Нет результата.", "error": state.get("error")}


def build_graph():
    g = StateGraph(AssistantState, input_schema=GraphInput, output_schema=GraphOutput)
    g.add_node("intake", intake_node)
    g.add_node("llm_extract", llm_extract_node)
    g.add_node("plan", plan_node)
    g.add_node("review", review_node)
    g.add_node("render", render_node)
    g.set_entry_point("intake")
    g.add_conditional_edges("intake", route_after_intake,
                            {"plan": "plan", "llm_extract": "llm_extract", "render": "render"})
    g.add_edge("llm_extract", "plan")
    g.add_edge("plan", "review")
    g.add_edge("review", "render")
    g.add_edge("render", END)
    return g.compile()


graph = build_graph()
