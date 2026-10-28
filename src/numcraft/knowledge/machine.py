"""Профиль станка (по умолчанию Haas VF-2)."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

_DIR = Path(__file__).parent


class Spindle(BaseModel):
    taper: str
    max_rpm: int
    min_rpm: int
    peak_power_kw: float
    peak_torque_nm: float
    base_rpm: int
    usable_power_ratio: float


class Vise(BaseModel):
    name: str
    jaw_width_mm: float
    max_opening_mm: float
    min_grip_mm: float
    recommended_grip_mm: float


class Machine(BaseModel):
    name: str
    control: str
    travel_mm: dict
    table_mm: dict
    spindle_nose_to_table_mm: dict
    spindle: Spindle
    max_cutting_feed_mm_min: int
    rapid_mm_min: int
    tool_changer: dict
    coolant: str
    vise: Vise

    def available_power_kw(self, rpm: float) -> float:
        """Длительно доступная мощность на данных оборотах (кривая постоянного момента до base_rpm)."""
        s = self.spindle
        torque_limited = s.peak_torque_nm * 2 * math.pi * rpm / 60 / 1000
        return min(s.peak_power_kw, torque_limited) * s.usable_power_ratio


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_machine(path: Optional[str] = None, max_rpm: Optional[int] = None) -> Machine:
    data = dict(_load(path or str(_DIR / "machine_haas_vf2.yaml")))
    machine = Machine.model_validate(data)
    if max_rpm:
        machine = machine.model_copy(deep=True)
        machine.spindle.max_rpm = int(max_rpm)
        if max_rpm > 8100:
            machine.name = f"{machine.name} ({max_rpm} об/мин)"
    return machine
