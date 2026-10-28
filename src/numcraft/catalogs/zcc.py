"""
Импорт каталогов ZCC Cutting Tools (PDF с текстовым слоем) в библиотеку NumCraft.

  python -m numcraft catalog taps  "ZCC-CT_Europe_HSS_tools_EN.pdf" -o knowledge/catalogs/zcc_taps.yaml
  python -m numcraft catalog text  "Main_Catalogue_2026_EN_w.pdf" -o zcc_main.txt --pages 200-420

`text` — выгрузка текста страниц (для большого каталога: файл в десятки раз меньше PDF,
его можно прислать для разработки импортёра фрез и свёрл).
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

TAP_ROW = re.compile(
    r"^(?P<article>4\d{3}U\w*-M[\d.*]+-6HX?)\s+(?P<chamfer>\dP)\s+M(?P<d>[\d,]+)\s+(?P<p>[\d,]+)\s+"
    r"(?P<d2>[\d,]+)\s+(?P<d3>[\d,]+)\s+(?P<l1>[\d,]+)\s+(?P<l2>[\d,]+)\s+(?P<l3>[\d,]+)\s+(?P<drill>[\d,]+)\s+"
    r"(?P<hg23>[●○–-])"
)


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def parse_pages(pages: Iterable[str]) -> List[dict]:
    """Строки таблиц метчиков ZCC: 4701US/4601US (глухие), 4702U/4602U (сквозные), 44xx (мелкий шаг)."""
    out: List[dict] = []
    for text in pages:
        shank = re.search(r"Shank type:\s*DIN\s*(\d+)", text)
        hole = "blind" if "Blind hole thread" in text else "through" if "Through hole thread" in text else None
        for line in text.splitlines():
            m = TAP_ROW.match(line.strip())
            if not m or hole is None:
                continue
            art = m.group("article")
            out.append({
                "article": art,
                "series": art.split("-")[0],
                "d": _f(m.group("d")), "pitch": _f(m.group("p")),
                "hole": hole,
                "form": "C (спиральная канавка 40°)" if hole == "blind" else "B (с подточкой)",
                "shank_din": int(shank.group(1)) if shank else None,
                "shank_d": _f(m.group("d2")),
                "l1": _f(m.group("l1")), "l2": _f(m.group("l2")), "l3": _f(m.group("l3")),
                "core_drill": _f(m.group("drill")),
                "internal_coolant": bool(re.match(r"4\d{3}UC", art)),
                "in_stock": m.group("hg23") == "●",
                "grade": "HG23 (HSS-E, TiAlN)",
            })
    return out


def parse_taps_pdf(path: str) -> List[dict]:
    from numcraft.parsers.drawing import open_pdf

    return parse_pages(p.extract_text() or "" for p in open_pdf(path).pages)


def _page_range(spec: Optional[str], n: int) -> List[int]:
    if not spec:
        return list(range(n))
    out: List[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out += list(range(max(lo, 1) - 1, min(hi, n)))
    return out


def dump_text(path: str, out_path: str, pages: Optional[str] = None) -> int:
    """Текст выбранных страниц PDF в файл; возвращает число страниц."""
    from numcraft.parsers.drawing import open_pdf

    reader = open_pdf(path)
    idx = _page_range(pages, len(reader.pages))
    print(f"  страниц: {len(idx)} из {len(reader.pages)}", flush=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for i in idx:
            f.write(f"\n===== PAGE {i + 1} =====\n")
            try:
                f.write(reader.pages[i].extract_text() or "")
            except Exception as e:  # битая страница не должна останавливать выгрузку всего каталога
                f.write(f"[не удалось извлечь текст: {e}]")
            if (i + 1) % 50 == 0:
                print(f"  … {i + 1} стр.", flush=True)
    return len(idx)
