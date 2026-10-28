"""
Состояние графа «помощник технолога»: вход (деталь) → техкарта.
"""
from typing import Any, Dict, List, Optional, TypedDict


class GraphInput(TypedDict, total=False):
    text: str  # описание детали на русском
    step_path: str  # путь к STEP
    drawing_path: str  # чертёж: PDF/DXF/TXT или изображение (PNG/JPG — только с use_llm)
    part_json: str  # деталь в схеме Part (JSON)
    material: str
    name: str
    gcode: bool  # добавить черновик УП
    dialect: str  # fanuc | haas
    max_rpm: int  # 12000 — для опционального шпинделя
    use_llm: bool  # разрешить LLM: извлечение из свободного текста/скана и комментарий технолога


class GraphOutput(TypedDict, total=False):
    techsheet_md: str
    techsheet: Dict[str, Any]
    gcode: Optional[str]
    questions: List[str]
    risks: List[Dict[str, str]]
    step_summary: Optional[str]
    review: Optional[str]
    error: Optional[str]


class AssistantState(GraphInput, GraphOutput, total=False):
    part: Optional[Dict[str, Any]]
    notes: List[str]
    missing: List[str]
