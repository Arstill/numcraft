"""
Системы координат граней детали.

Деталь: X0 Y0 — левый передний угол (вид сверху), Z0 — верх, деталь в −Z.
Координаты элемента на грани — (u, v) «как смотришь на грань», d — глубина от плоскости грани внутрь:
  top    — u = x,     v = y      (вид сверху)
  bottom — u = x,     v = y      (тоже вид сверху; переворот учитывает установ)
  front  — u = x,     v = z + Z  (передняя грань, −Y; v — высота от низа)
  back   — u = X − x, v = z + Z  (задняя грань, +Y)
  left   — u = Y − y, v = z + Z  (левая грань, −X)
  right  — u = y,     v = z + Z  (правая грань, +X)
Установ на грань: X станка = u, Y станка = v, Z0 — плоскость грани (для низа — переворот вокруг X).
"""
from __future__ import annotations

from typing import Tuple

from numcraft.models import Box

Vec = Tuple[float, float, float]
SIDE_SETUP_ORDER = ("top", "bottom", "front", "back", "left", "right")


def face_dims(side: str, size: Box) -> Vec:
    """(ширина u, высота v, глубина до противоположной грани)."""
    X, Y, Z = size.x, size.y, size.z
    if side in ("top", "bottom"):
        return X, Y, Z
    if side in ("front", "back"):
        return X, Z, Y
    return Y, Z, X


def to_face(side: str, x: float, y: float, z: float, size: Box) -> Vec:
    X, Y, Z = size.x, size.y, size.z
    return {
        "top": (x, y, -z),
        "bottom": (x, y, z + Z),
        "front": (x, z + Z, y),
        "back": (X - x, z + Z, Y - y),
        "left": (Y - y, z + Z, x),
        "right": (y, z + Z, X - x),
    }[side]


def from_face(side: str, u: float, v: float, d: float, size: Box) -> Vec:
    X, Y, Z = size.x, size.y, size.z
    return {
        "top": (u, v, -d),
        "bottom": (u, v, -Z + d),
        "front": (u, d, v - Z),
        "back": (X - u, Y - d, v - Z),
        "left": (d, Y - u, v - Z),
        "right": (X - d, u, v - Z),
    }[side]


def to_setup(side: str, x: float, y: float, z: float, size: Box) -> Vec:
    """Координаты станка в установе на грань (нуль — левый передний угол грани, Z0 — грань)."""
    if side == "top":
        return x, y, z
    if side == "bottom":
        return x, size.y - y, -size.z - z
    u, v, d = to_face(side, x, y, z, size)
    return u, v, -d
