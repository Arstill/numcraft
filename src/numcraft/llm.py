"""
Необязательный LLM-слой (OpenAI-совместимый endpoint, конфиг config/agent_llm_config.json).

LLM используется только там, где нужен «глаз технолога»:
  1. extract_part — разобрать свободный текст или изображение чертежа в схему Part (structured output);
  2. review — короткий комментарий к готовой техкарте (что уточнить, на что обратить внимание).
Числа (обороты, подачи, глубины, циклы) LLM не назначает — их считает planner/cutting.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional

from numcraft.models import Part, TechSheet
from numcraft.techsheet import to_markdown

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "agent_llm_config.json"

EXTRACT_PROMPT = """Ты — технолог по фрезерной обработке. Преобразуй описание/чертёж детали в JSON по схеме Part.
Правила:
- Размеры в мм. X0 Y0 — левый передний угол детали на виде сверху, Z0 — верх детали.
- material — марка как на чертеже (6061, 7075, сталь 45, 1045).
- Резьбы — type=thread (size "M6", depth — длина резьбы). Отверстия под развёртку — fit "H7".
- Элементы снизу детали — side="bottom" (координаты всё равно в виде сверху).
- Не выдумывай размеры: если величины нет — не заполняй поле.
"""

REVIEW_PROMPT = """Ты — опытный технолог-программист ЧПУ (Haas VF-2, HSMWorks). Ниже техкарта, рассчитанная программой.
Дай короткий комментарий на русском (до 10 пунктов): что проверить на чертеже, где возможны проблемы
с креплением/жёсткостью, что бы ты сделал иначе. Не меняй числовые режимы — только замечания.
"""


def make_llm(ctx: Any = None, streaming: bool = False):
    from langchain_openai import ChatOpenAI

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))["config"]
    headers = {}
    if ctx is not None:
        try:
            from coze_coding_utils.runtime_ctx.context import default_headers

            headers = default_headers(ctx)
        except ImportError:
            pass
    return ChatOpenAI(
        model=os.getenv("NUMCRAFT_MODEL", cfg.get("model")),
        api_key=os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("COZE_INTEGRATION_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        temperature=0.1,
        streaming=streaming,
        timeout=cfg.get("timeout", 600),
        default_headers=headers,
    )


def _image_part(path: str) -> dict:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def extract_part(llm, text: Optional[str] = None, image_path: Optional[str] = None) -> Part:
    from langchain_core.messages import HumanMessage, SystemMessage

    content: list = [{"type": "text", "text": text or "Разбери чертёж на изображении."}]
    if image_path:
        content.append(_image_part(image_path))
    structured = llm.with_structured_output(Part)
    return structured.invoke([SystemMessage(content=EXTRACT_PROMPT), HumanMessage(content=content)])


def review(llm, sheet: TechSheet) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    md = to_markdown(sheet, details=False)
    msg = llm.invoke([SystemMessage(content=REVIEW_PROMPT), HumanMessage(content=md)])
    return getattr(msg, "content", str(msg))
