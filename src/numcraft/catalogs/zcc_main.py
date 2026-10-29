"""
Импорт основного каталога ZCC (текст, выгруженный `numcraft catalog text`) — твёрдосплавные фрезы,
свёрла, центровки, фасочники, развёртки.

Особенность текста из PDF: в части строк пропадают пробелы между цифрами
(«AL-3E-D1.0 143 5 0 3A» = D1 d4 H3 L50 z3). Порядок символов при этом сохраняется, поэтому
такие строки восстанавливаются по шаблону длин соседних «чистых» строк той же таблицы и
проверяются по диаметру из артикула и правдоподобию размеров.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Серии, которые нужны планировщику (Haas VF-2, алюминий 6061/7075, сталь 45/1045)
SERIES: Dict[str, dict] = {
    # концевые фрезы
    "AL-3E": {"kind": "end_mill", "group": "aluminum", "length": "std"},
    "AL-3EL": {"kind": "end_mill", "group": "aluminum", "length": "long"},
    "AL-2E": {"kind": "end_mill", "group": "aluminum", "length": "std", "spare": True},
    "AL-2EL": {"kind": "end_mill", "group": "aluminum", "length": "long", "spare": True},
    "UM-4E": {"kind": "end_mill", "group": "steel", "length": "std"},
    "UM-4EL": {"kind": "end_mill", "group": "steel", "length": "long"},
    "GM-4E": {"kind": "end_mill", "group": "steel", "length": "std", "spare": True},
    "GM-4EL": {"kind": "end_mill", "group": "steel", "length": "long", "spare": True},
    "GM-4EFP": {"kind": "end_mill", "group": "steel", "length": "neck"},
    "GM-2EFP": {"kind": "end_mill", "group": "any", "length": "neck"},
    # сферические
    "AL-2B": {"kind": "ball_mill", "group": "aluminum"},
    "GM-2B": {"kind": "ball_mill", "group": "steel"},
    # свёрла (C — с внутренним подводом СОЖ)
    "1534SU03": {"kind": "drill", "group": "any", "xd": 3},
    "1536SU05": {"kind": "drill", "group": "any", "xd": 5},
    "1538SU08C": {"kind": "drill", "group": "any", "xd": 8},
    "1105SC03": {"kind": "drill", "group": "aluminum", "xd": 3},
    "1101SC05": {"kind": "drill", "group": "aluminum", "xd": 5},
    # центровка NC 90°, фасочник 90°, развёртка
    "1143SC90": {"kind": "spot_drill", "group": "any"},
    "5601R90": {"kind": "chamfer_mill", "group": "any"},
    "5501R90": {"kind": "chamfer_mill", "group": "any", "spare": True},
    "3112H7": {"kind": "reamer", "group": "any"},
}

MARKS = {"Ɣ": True, "ż": False, "●": True, "○": False}
LABEL_RE = re.compile(r"(?m)^([A-E]) ?(\d{1,3})\s*$")
STD_SHANKS = {3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 25, 32}


def split_pages(text: str) -> List[Tuple[int, str]]:
    parts = re.split(r"\n===== PAGE (\d+) =====\n", text)
    return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]


def _header_cols(line: str) -> List[str]:
    s = re.sub(r"\([^)]*\)", " ", line[len("Article"):])
    s = re.sub(r"\b([dl]) (\d)\b", r"\1\2", s)  # «d 2» → d2, «l 1» → l1
    toks = []
    for t in s.split():
        if t in ("HML", "HL"):
            toks += list(t)
        else:
            toks.append(t)
    return toks


def _series_of(article: str) -> Optional[str]:
    best = None
    for s in SERIES:
        if article.startswith(s) and (len(article) == len(s) or not article[len(s)].isalpha()
                                      or s.endswith("R90")):
            if best is None or len(s) > len(best):
                best = s
    return best


def _article_d(article: str, kind: str) -> Optional[float]:
    m = re.search(r"-D(\d+(?:\.\d+)?)S?$", article)
    if m:
        return float(m.group(1))
    m = re.search(r"-(\d{4})(?:S)?$", article)
    if m:
        return int(m.group(1)) / 100
    return None


def _segment(chars: str, lens: List[int]) -> Optional[List[str]]:
    if sum(lens) != len(chars):
        return None
    out, i = [], 0
    for n in lens:
        out.append(chars[i:i + n])
        i += n
    return out


def _repair(body: str, art: str, kind: str, cols: List[str], templates: List[List[int]]) -> Optional[List[str]]:
    """Склеенная строка: первый столбец — диаметр из артикула, остальное режем по шаблону соседних строк."""
    chars = body.replace(" ", "")
    ad = _article_d(art, kind)
    first = cols[0] if cols else ""
    lead = None
    if ad is not None and first in ("D", "d1", "d"):
        lead = f"{ad:.3f}".rstrip("0").rstrip(".")
        if not chars.startswith(lead):
            return None
        chars = chars[len(lead):]
    for lens in templates:
        rest = lens[1:] if lead is not None else lens
        seg = _segment(chars, rest)
        if seg:
            return ([lead] if lead is not None else []) + seg
    return None


def _num(s: str) -> Optional[float]:
    try:
        return float(s)
    except ValueError:
        return None


def _plausible(rec: dict) -> bool:
    d, oal = rec.get("d"), rec.get("oal")
    if not d or not oal or oal < 30 or oal > 400:
        return False
    if rec.get("shank_d") and (rec["shank_d"] < 2.5 or rec["shank_d"] > 40):
        return False
    lc = rec.get("lc")
    if lc is not None and not (0 < lc < oal):
        return False
    if rec.get("reach") and rec["reach"] >= oal:
        return False
    return True


def parse(text: str) -> List[dict]:
    out: List[dict] = []
    for _, page in split_pages(text):
        lines = page.splitlines()
        hdr = next((l for l in lines if l.startswith("Article ")), None)
        if not hdr:
            continue
        cols = _header_cols(hdr)
        grade_cols = [c for c in cols if re.match(r"^(K[A-Z]{2}\d{3,4}|YK\d{2}F)$", c)]
        dim_cols = [c for c in cols if c not in grade_cols]
        start = lines.index(hdr) + 1
        rows: List[Tuple[str, str, List[str]]] = []
        for line in lines[start:]:
            if line.startswith("Ɣ") or line.startswith("ƔEx"):
                break
            m = re.match(r"^(\S+)\s+(.*)$", line.strip())
            if not m or not _series_of(m.group(1)):
                continue
            # -W — хвостовик Weldon, -G — другая геометрия (GM-4E-G), -R.. — фрезы-скругления
            if re.search(r"-(W|G)$", m.group(1)):
                continue
            art, rest = m.group(1), m.group(2)
            marks = [MARKS[c] for c in rest if c in MARKS]
            body = "".join(c for c in rest if c not in MARKS).strip()
            rows.append((art, body, marks))
        # «чистые» строки — шаблоны длин токенов
        clean = {}
        for i, (art, body, _) in enumerate(rows):
            toks = body.split()
            if len(toks) == len(dim_cols):
                clean[i] = [len(t) for t in toks]
        for i, (art, body, marks) in enumerate(rows):
            series = _series_of(art)
            meta = SERIES[series]
            toks = body.split()
            if len(toks) != len(dim_cols):
                toks = _repair(body, art, meta["kind"], dim_cols, [clean[j] for j in
                                                                   sorted(clean, key=lambda j: abs(j - i))])
                if toks is None:
                    continue
            vals = dict(zip(dim_cols, toks))
            rec = _record(art, series, meta, vals, marks)
            rm = re.search(r"-R(\d+)-", art)
            if rec and rm and meta["kind"] == "chamfer_mill":
                # 5601R904FM-R20-1000 — фреза-скругление R2.0 (R075 → 0.75)
                dg = rm.group(1)
                rec.update(kind="round_mill", r=float("0." + dg[1:]) if dg.startswith("0") else int(dg) / 10)
            if rec and grade_cols:
                rec["grade"] = grade_cols[0]
            if rec and _plausible(rec):
                ad = _article_d(art, meta["kind"])
                if ad is None or abs(ad - rec["d"]) < 0.011:
                    out.append(rec)
    return out


def _record(art: str, series: str, meta: dict, v: Dict[str, str], marks: List[bool]) -> Optional[dict]:
    kind = meta["kind"]
    g = _num
    rec: dict = {"article": art, "series": series, "kind": kind, "group": meta["group"],
                 "in_stock": bool(marks and marks[0]), "spare": meta.get("spare", False)}
    if kind in ("end_mill", "ball_mill"):
        rec.update(d=g(v.get("D", "")), shank_d=g(v.get("d", "")), lc=g(v.get("H", "")), oal=g(v.get("L", "")),
                   z=int(g(v.get("Teeth", "0")) or 0), length=meta.get("length", "std"))
        if "M" in v:  # фреза с шейкой: d1 — Ø шейки, M — длина шейки (вылет)
            rec.update(neck_d=g(v["d1"]), reach=g(v["M"]))
        if "R" in v:
            rec["r"] = g(v["R"])
    elif kind == "drill":
        rec.update(d=g(v.get("d1", "")), shank_d=g(v.get("d2", "")), oal=g(v.get("l1", "")),
                   lc=g(v.get("l2", "")), reach=g(v.get("l3", "")) if "l3" in v else None, xd=meta["xd"],
                   internal_coolant=series.endswith("C") or bool(re.match(r"^\d{4}\w+C-", art)))
        if rec["reach"] is None and rec["lc"]:
            rec["reach"] = round(rec["lc"] * 0.8, 1)
    elif kind == "spot_drill":
        rec.update(d=g(v.get("d1", "")), shank_d=g(v.get("d2", "")), oal=g(v.get("l1", "")), lc=g(v.get("l2", "")),
                   angle=90)
    elif kind == "chamfer_mill":
        rec.update(d=g(v.get("d", "")), shank_d=g(v.get("d", "")), oal=g(v.get("L", "")), tip_d=g(v.get("D", "")),
                   angle=g(v.get("X", "90")), z=int(g(v.get("Teeth", "0")) or 0), lc=None)
    elif kind == "reamer":
        rec.update(d=g(v.get("d1", "")), shank_d=g(v.get("d2", "")), oal=g(v.get("l1", "")), lc=g(v.get("l3", "")),
                   reach=g(v.get("l2", "")), z=int(g(v.get("Teeth", "0")) or 0), fit="H7")
    if rec.get("d") is None:
        return None
    return {k: val for k, val in rec.items() if val is not None}


def build_yaml(text: str) -> str:
    import yaml

    rows = parse(text)
    hdr = ("# Инструмент ZCC-CT из основного каталога (Main Catalogue 2026): твёрдосплавные фрезы, свёрла,\n"
           "# центровки NC 90°, фасочники 90°, развёртки H7. Создано: python -m numcraft catalog main <txt>.\n"
           "# d — диаметр, shank_d — хвостовик, lc — длина режущей части (свёрла — длина канавки),\n"
           "# reach — рабочая длина (свёрла — l3, фрезы с шейкой — длина шейки M), oal — общая длина.\n")
    return hdr + yaml.safe_dump({"catalog": "ZCC-CT Main Catalogue 2026", "tools": rows}, allow_unicode=True,
                                sort_keys=False, width=140)
