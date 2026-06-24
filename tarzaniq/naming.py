"""Folder-name parsing (YY.MM.DD.Place.Name) and Sony filename
sequence analysis for detecting deleted photos."""

import re
from datetime import date

JPEG_EXTS = {".jpg", ".jpeg", ".jpe"}

_SEQ_RE = re.compile(r"(\d{4,5})(?=\.[A-Za-z]+$)")  # trailing digits before extension
_PREFIX_RE = re.compile(r"^([A-Za-z_]*)")


class FolderNameError(ValueError):
    pass


def parse_folder_name(name: str):
    """YY.MM.DD.Place.Name  ->  (date, place, employee)

    Forgiving on extra dots: first three parts are the date, the LAST part
    is the employee name, anything in between joins into the place.
    """
    parts = [p.strip() for p in name.split(".") if p.strip() != ""]
    if len(parts) < 5:
        raise FolderNameError(
            f"'{name}' doesn't match YY.MM.DD.Place.Name "
            "(example: 26.06.11.CityPark.Marko)")
    yy, mm, dd = parts[0], parts[1], parts[2]
    if not (yy.isdigit() and mm.isdigit() and dd.isdigit()):
        raise FolderNameError(
            f"'{name}': the first three parts must be numbers (YY.MM.DD)")
    year = int(yy)
    year = 2000 + year if year < 100 else year
    try:
        d = date(year, int(mm), int(dd))
    except ValueError:
        raise FolderNameError(
            f"'{name}': {yy}.{mm}.{dd} isn't a real calendar date")
    employee = parts[-1]
    place = ".".join(parts[3:-1])
    if not place or not employee:
        raise FolderNameError(
            f"'{name}': place or name part is empty")
    return d, place, employee


def filename_seq(filename: str):
    """Extract (prefix, sequence_number) from e.g. DSC04231.JPG -> ('DSC', 4231)."""
    m = _SEQ_RE.search(filename)
    if not m:
        return None, None
    num = int(m.group(1))
    prefix = filename[: m.start(1)]
    return prefix, num


def detect_deletions(entries):
    """entries: list of (filename, sort_time) already in chronological order.

    Returns dict with suspected deletion count + gap details, handling
    Sony's 9999 -> 0001 filename wrap. Sequences are grouped by filename
    prefix so a mid-day camera/body change doesn't create phantom gaps.
    """
    by_prefix = {}
    for fn, t in entries:
        prefix, num = filename_seq(fn)
        if num is None:
            continue
        by_prefix.setdefault(prefix, []).append((t, fn, num))

    total_missing = 0
    gaps = []
    for prefix, rows in by_prefix.items():
        rows.sort(key=lambda r: (r[0], r[1]))
        for (t1, f1, n1), (t2, f2, n2) in zip(rows, rows[1:]):
            diff = (n2 - n1) % 10000  # Sony wraps 9999 -> 0001 (0000 unused)
            if diff in (0, 1):
                continue
            missing = diff - 1
            if n2 < n1:
                missing -= 1  # the wrap skips 0000; don't count it as deleted
            if missing <= 0:
                continue
            if missing > 800:
                # enormous jump: almost certainly a card reused across many days
                # or a counter reset, not 800 deletions. Flag, don't count.
                gaps.append({"after": f1, "before": f2, "missing": None,
                             "note": "sequence jump too large to be deletions"})
                continue
            total_missing += missing
            gaps.append({"after": f1, "before": f2, "missing": missing})
    return {"suspected_deletions": total_missing, "gaps": gaps,
            "prefixes": sorted(by_prefix.keys())}
