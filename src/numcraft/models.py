"""
Модель данных: деталь (вход) и техкарта (выход).

Все размеры в миллиметрах. Координаты признаков задаются в системе детали:
X0 Y0 — левый передний угол готовой детали (вид сверху), Z0 — верх готовой детали.
"""
from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field

Side = Literal["top", "bottom", "front", "back", "left", "right"]

SIDE_RU: Dict[str, str] = {
    "top": "верх (сторона A)",
    "bottom": "низ (сторона B)",
    "front": "передняя грань",
    "back": "задняя грань",
    "left": "левая грань",
    "right": "правая грань",
}

Point2D = Tuple[float, float]


class _FeatureBase(BaseModel):
    id: str = ""
    side: Side = "top"
    note: str = ""


class FaceFeature(_FeatureBase):
    """Торцовка верхней плоскости (снимается припуск заготовки)."""
    type: Literal["face"] = "face"
    ra: Optional[float] = None


class ContourFeature(_FeatureBase):
    """Наружный контур детали (по умолчанию — габарит length × width)."""
    type: Literal["contour"] = "contour"
    length: Optional[float] = None
    width: Optional[float] = None
    depth: Optional[float] = None  # высота стенки; по умолчанию — толщина детали
    corner_radius: float = 0.0
    tolerance: Optional[float] = None  # ± мм на размер
    ra: Optional[float] = None


class PocketFeature(_FeatureBase):
    """Закрытый (или открытый с одной стороны) карман."""
    type: Literal["pocket"] = "pocket"
    length: float
    width: float
    depth: float
    corner_radius: float = 0.0
    floor_radius: float = 0.0
    through: bool = False
    open_side: bool = False
    count: int = 1
    center: Optional[Point2D] = None
    along: Literal["x", "y"] = "x"  # вдоль какой оси длинная сторона
    tolerance: Optional[float] = None
    ra: Optional[float] = None


class SlotFeature(_FeatureBase):
    type: Literal["slot"] = "slot"
    length: float
    width: float
    depth: float
    through: bool = False
    open_ends: bool = False
    count: int = 1
    center: Optional[Point2D] = None
    along: Literal["x", "y"] = "x"
    tolerance: Optional[float] = None
    ra: Optional[float] = None


class Counterbore(BaseModel):
    diameter: float
    depth: float


class HoleFeature(_FeatureBase):
    type: Literal["hole"] = "hole"
    diameter: float
    depth: Optional[float] = None  # для сквозных — толщина в месте отверстия
    through: bool = True
    count: int = 1
    positions: List[Point2D] = Field(default_factory=list)
    z_start: float = 0.0  # Z поверхности входа (отрицательная — отверстие в дне кармана)
    fit: Optional[str] = None  # квалитет, напр. "H7"
    ra: Optional[float] = None
    counterbore: Optional[Counterbore] = None
    chamfer: Optional[float] = None


class ThreadFeature(_FeatureBase):
    type: Literal["thread"] = "thread"
    size: str  # "M6", "M10x1"
    depth: Optional[float] = None  # длина резьбы
    through: bool = False
    count: int = 1
    positions: List[Point2D] = Field(default_factory=list)
    z_start: float = 0.0
    method: Literal["auto", "tap", "thread_mill"] = "auto"


class ChamferFeature(_FeatureBase):
    type: Literal["chamfer"] = "chamfer"
    size: float = 0.5
    edges: Literal["outer", "all", "pockets", "holes"] = "outer"


class SurfaceFeature(_FeatureBase):
    """Произвольная 3D-поверхность (галтели переменного радиуса, формы)."""
    type: Literal["surface3d"] = "surface3d"
    description: str = ""
    length: Optional[float] = None
    width: Optional[float] = None
    depth: Optional[float] = None
    min_concave_radius: Optional[float] = None
    ra: Optional[float] = None


Feature = Annotated[
    Union[
        FaceFeature,
        ContourFeature,
        PocketFeature,
        SlotFeature,
        HoleFeature,
        ThreadFeature,
        ChamferFeature,
        SurfaceFeature,
    ],
    Field(discriminator="type"),
]


class Box(BaseModel):
    x: float
    y: float
    z: float

    def fmt(self) -> str:
        return f"{_n(self.x)}×{_n(self.y)}×{_n(self.z)} мм"


class Part(BaseModel):
    name: str = "Деталь"
    material: str
    size: Box  # габарит готовой детали
    stock: Optional[Box] = None  # заготовка; если нет — назначается автоматически
    quantity: int = 1
    features: List[Feature] = Field(default_factory=list)
    general_tolerance: Optional[str] = None  # напр. "ISO 2768-m"
    datum: Literal["corner", "center"] = "corner"
    notes: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Выход
# ---------------------------------------------------------------------------

class Tool(BaseModel):
    kind: str  # face_mill, end_mill, bull_mill, ball_mill, spot_drill, drill, tap, reamer, chamfer_mill, thread_mill
    diameter: float
    flutes: int = 2
    flute_length: float = 0.0
    overall_length: float = 0.0
    corner_radius: float = 0.0
    tool_material: str = "твердый сплав"
    coating: str = ""
    for_group: str = "any"  # aluminum / steel / any
    pitch: Optional[float] = None  # метчик / резьбофреза
    thread: Optional[str] = None
    point_angle: Optional[float] = None
    description: str = ""
    number: int = 0  # T-номер, назначается планировщиком
    stickout: float = 0.0  # рекомендуемый вылет из патрона

    def key(self) -> Tuple:
        return (self.kind, round(self.diameter, 3), self.flutes, self.corner_radius,
                self.for_group, self.thread, self.flute_length)

    def label(self) -> str:
        return self.description or f"{self.kind} Ø{_n(self.diameter)}"


class CuttingData(BaseModel):
    vc: float  # м/мин (фактическая)
    rpm: int
    feed: float  # мм/мин (для нарезания резьбы — точно S×P)
    fz: Optional[float] = None  # мм/зуб (запрограммированная)
    f_rev: Optional[float] = None  # мм/об
    ap: Optional[float] = None
    ae: Optional[float] = None
    plunge_feed: Optional[float] = None
    power_kw: Optional[float] = None
    coolant: str = "СОЖ (M08)"
    limits: List[str] = Field(default_factory=list)  # чем ограничен режим


class Operation(BaseModel):
    number: int = 0
    title: str
    strategy: str  # название стратегии HSMWorks
    tool: Tool
    cutting: CuttingData
    feature_ids: List[str] = Field(default_factory=list)
    params: Dict[str, str] = Field(default_factory=dict)  # параметры стратегии HSMWorks
    cycle: Optional[str] = None  # G81/G73/G83/G84/G85
    z_depth: Optional[float] = None  # конечная глубина, мм (отрицательная)
    z_start: float = 0.0  # Z поверхности входа (для R-плоскости циклов)
    positions: List[Point2D] = Field(default_factory=list)
    peck: Optional[float] = None
    notes: List[str] = Field(default_factory=list)
    stage: int = 0  # порядок сортировки внутри установа
    geom: str = ""  # что обрабатывается (для схемы): face, outer_rough, pocket_walls, holes…
    selection: str = ""  # что выбрать в HSMWorks


class Setup(BaseModel):
    number: int
    side: Side
    title: str
    wcs: str = "G54"
    stock_top: float = 0.0  # высота заготовки над Z0 в начале установа, мм
    workholding: List[str]
    datum: List[str]
    operations: List[Operation] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class Risk(BaseModel):
    level: Literal["высокий", "средний", "низкий"]
    topic: str
    message: str
    action: str


class TechSheet(BaseModel):
    part: Part
    machine: str
    material: str
    stock: Box
    setups: List[Setup]
    tools: List[Tool]
    risks: List[Risk] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)
    gcode: Optional[str] = None


def _n(v: float) -> str:
    """Короткое представление числа: 10.0 → '10', 6.60 → '6.6'."""
    return f"{v:.3f}".rstrip("0").rstrip(".")
