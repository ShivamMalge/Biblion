#!/usr/bin/env python3
"""Regenerate the sample page images used in README.md.

The README's whole claim is that the output looks good, so the images have to
come from a real build rather than being hand-made -- and they have to be easy
to refresh, or they will quietly drift from what Biblion actually produces.

    python scripts/screenshots.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "diagram-tour"
PDF = EXAMPLE / "output" / "DiagramTour.pdf"
REPORT_PDF = EXAMPLE / "output" / "DiagramTour_report.pdf"
IMAGES = ROOT / "docs" / "images"

# Page index (0-based) -> file name. Kept explicit rather than guessed, so a
# change in the example's pagination shows up as an obviously wrong picture
# instead of a silently different one.
PAGES = {
    0: "cover",
    1: "contents",
    2: "figures",
    3: "page-with-figure",
    4: "d2-containment",
}

# One page per theme, so the README can show what the choice actually means.
THEME_PAGES = {"textbook": 3, "report": 3}

DPI = 110


def _build(*extra: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "biblion", "build", str(EXAMPLE), "--strict",
         *extra], cwd=ROOT).returncode


def main() -> int:
    print(f"Building {EXAMPLE.name} ...")
    if (rc := _build()) != 0:
        print("Build failed; not regenerating screenshots.", file=sys.stderr)
        return rc

    print("Building it again with the report theme ...")
    if (rc := _build("--theme", "report",
                     "--output", "output/DiagramTour_report.pdf")) != 0:
        print("Report-theme build failed.", file=sys.stderr)
        return rc

    IMAGES.mkdir(parents=True, exist_ok=True)
    book = fitz.open(PDF)
    print(f"{PDF.name}: {book.page_count} pages")

    for index, name in PAGES.items():
        if index >= book.page_count:
            print(f"  ! page {index + 1} does not exist, skipping {name}",
                  file=sys.stderr)
            continue
        target = IMAGES / f"{name}.png"
        book[index].get_pixmap(dpi=DPI).save(str(target))
        print(f"  wrote {target.relative_to(ROOT)}")

    # A same-page comparison of the two themes.
    for theme, index in THEME_PAGES.items():
        source = PDF if theme == "textbook" else REPORT_PDF
        doc = fitz.open(source)
        if index < doc.page_count:
            target = IMAGES / f"theme-{theme}.png"
            doc[index].get_pixmap(dpi=DPI).save(str(target))
            print(f"  wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
