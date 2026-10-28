"""База материалов и режимов резания."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import yaml
from pydantic import BaseModel

_DIR = Path(__file__).parent


class Material(BaseModel):
    key: str
    name: str
    aliases: List[str]
    group: str  # aluminum / steel
    hardness: str
    kc: float  # удельная сила резания, Н/мм²
    coolant: str
    milling: dict
    face_mill: dict
    drill: dict
    spot_drill: dict
    tap: dict
    reamer: dict
    chamfer_mill: dict
    thread_mill: dict
    ball_mill: dict
    notes: List[str] = []

    @property
    def is_aluminum(self) -> bool:
        return self.group == "aluminum"


class UnknownMaterial(ValueError):
    pass


@lru_cache(maxsize=1)
def all_materials() -> Dict[str, Material]:
    with open(_DIR / "materials.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {k: Material(key=k, **v) for k, v in data["materials"].items()}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("ё", "е")).strip()


def resolve_material(text: str) -> Material:
    """Найти материал по названию/марке: '6061', 'Д16'… (поиск по псевдонимам, длинные — первыми)."""
    t = _norm(text)
    mats = all_materials()
    if t in mats:
        return mats[t]
    pairs = sorted(
        ((alias, m) for m in mats.values() for alias in m.aliases),
        key=lambda p: -len(p[0]),
    )
    for alias, m in pairs:
        if alias == t:
            return m
    for alias, m in pairs:
        # короткие числовые марки ("45") — только как отдельное слово
        if re.search(rf"(?<![\w.]){re.escape(alias)}(?![\w.])", t):
            return m
    supported = ", ".join(m.name for m in mats.values())
    raise UnknownMaterial(f"Материал «{text}» не найден. Поддерживаются: {supported}.")
