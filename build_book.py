#!/usr/bin/env python3
"""
build_book.py
--------------
Turns a folder of module markdown files into a single, styled PDF
"textbook" — reusable for every Coursera course, at zero AI cost per run.

USAGE
-----
1. Ask Claude to write CONTENT-ONLY markdown per module (see prompt
   template in README.md). Save each as 01_module1.md, 02_module2.md, ...
   inside a folder, e.g. course09_mcp/modules/

2. In your markdown, mark callout boxes with admonition syntax:

       !!! deepdive "Why MCP exists"
           A language model is a brain in a jar...

       !!! interview "Likely question"
           Q: How does MCP differ from a plain REST API?
           A: ...

       !!! workhelp "When to use what"
           Use STDIO when the server is local...

   (types: deepdive, interview, workhelp, note, tip)

3. For diagrams, use fenced ```mermaid blocks as normal — this script
   will render them to SVG locally via mermaid-cli (mmdc) if installed,
   or fall back to leaving the code block as text if mmdc is missing.

4. Run:
       python3 build_book.py --input course09_mcp/modules \
                              --output course09_mcp/BuildAIAgentsUsingMCP.pdf \
                              --title "Build AI Agents using MCP" \
                              --subtitle "Course 9 of the IBM RAG and Agentic AI Professional Certificate" \
                              --student "Shivam" \
                              --course-num 9

   Add --per-module to ALSO emit one PDF per module alongside the merged book.

This script costs $0 and no AI credits per run — the styling is baked
into textbook.css and this script; you only ever pay for the markdown
content generation once.
"""

import argparse
import datetime
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown
from weasyprint import HTML

MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)
D2_BLOCK_RE = re.compile(r"```d2\n(.*?)\n```", re.DOTALL)


def _svg_to_png(svg_path: Path, png_path: Path, width: int = 1200) -> bool:
    """Convert an SVG to PNG via rsvg-convert. Far more reliable than
    embedding SVG directly — both WeasyPrint's and cairosvg's SVG engines
    choke on real-world SVGs (nested <svg>, embedded webfonts, etc.) that
    rsvg-convert (the standard librsvg renderer) handles correctly."""
    has_rsvg = shutil.which("rsvg-convert") is not None
    if not has_rsvg:
        return False
    result = subprocess.run(
        ["rsvg-convert", "-o", str(png_path), "-w", str(width),
         "--background-color=white", str(svg_path)],
        capture_output=True, text=True,
    )
    return png_path.exists()


def render_d2_blocks(md_text: str, work_dir: Path) -> str:
    """Replace ```d2 fenced blocks with rendered PNGs via the d2 CLI."""
    has_d2 = shutil.which("d2") is not None

    def _replace(match):
        code = match.group(1)
        digest = hashlib.sha1(code.encode()).hexdigest()[:10]
        if not has_d2:
            return f"```\n[DIAGRAM - install d2 (d2lang.com) to render]\n{code}\n```"

        d2_path = work_dir / f"d2_{digest}.d2"
        svg_path = work_dir / f"d2_{digest}.svg"
        png_path = work_dir / f"d2_{digest}.png"
        d2_path.write_text(code, encoding="utf-8")
        result = subprocess.run(
            ["d2", "--theme", "0", str(d2_path), str(svg_path)],
            capture_output=True, text=True,
        )
        if svg_path.exists() and _svg_to_png(svg_path, png_path):
            return f'<div class="diagram"><img src="{png_path.as_posix()}"></div>'
        print(f"  ⚠ D2 diagram render failed for block {digest}: "
              f"{result.stderr.strip().splitlines()[-1] if result.stderr else 'unknown error'}",
              file=sys.stderr)
        return f"```\n[D2 diagram render failed - see console output]\n{code}\n```"

    return D2_BLOCK_RE.sub(_replace, md_text)


def render_mermaid_blocks(md_text: str, work_dir: Path, puppeteer_config: str | None) -> str:
    """Replace ```mermaid fenced blocks with rendered PNGs (if mmdc available)."""
    has_mmdc = shutil.which("mmdc") is not None

    def _replace(match):
        code = match.group(1)
        digest = hashlib.sha1(code.encode()).hexdigest()[:10]
        if not has_mmdc:
            # Fallback: keep as a labeled code block so nothing is lost.
            return f"```\n[DIAGRAM - install mermaid-cli to render]\n{code}\n```"

        mmd_path = work_dir / f"diagram_{digest}.mmd"
        svg_path = work_dir / f"diagram_{digest}.svg"
        png_path = work_dir / f"diagram_{digest}.png"
        mmd_path.write_text(code, encoding="utf-8")
        cmd = ["mmdc", "-i", str(mmd_path), "-o", str(svg_path),
               "-b", "transparent", "-w", "1000"]
        if puppeteer_config:
            cmd += ["-p", puppeteer_config]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if svg_path.exists() and _svg_to_png(svg_path, png_path):
            return f'<div class="diagram"><img src="{png_path.as_posix()}"></div>'
        if svg_path.exists():
            # rsvg-convert unavailable — fall back to raw SVG embed (best effort).
            return f'<div class="diagram"><img src="{svg_path.as_posix()}"></div>'
        print(f"  ⚠ Mermaid diagram render failed for block {digest}: "
              f"{result.stderr.strip().splitlines()[-1] if result.stderr else 'unknown error'}",
              file=sys.stderr)
        return f"```\n[diagram render failed - see console output]\n{code}\n```"

    return MERMAID_BLOCK_RE.sub(_replace, md_text)


def md_to_html_body(md_text: str, work_dir: Path, puppeteer_config: str | None) -> str:
    md_text = render_mermaid_blocks(md_text, work_dir, puppeteer_config)
    md_text = render_d2_blocks(md_text, work_dir)
    return markdown.markdown(
        md_text,
        extensions=[
            "extra",            # tables, fenced_code, footnotes, etc.
            "admonition",        # !!! callout boxes
            "codehilite",        # syntax highlighting
            "toc",                # heading ids for TOC links
            "sane_lists",
        ],
        extension_configs={
            "codehilite": {"css_class": "codehilite", "guess_lang": False},
            "toc": {"anchorlink": False},
        },
    )


def build_toc(html_body: str) -> str:
    """Extract h1/h2/h3 and build a simple linked TOC block."""
    heading_re = re.compile(r'<h([123]) id="([^"]+)">(.*?)</h\1>')
    items = []
    for level, hid, text in heading_re.findall(html_body):
        clean = re.sub(r"<[^>]+>", "", text)
        items.append((int(level), hid, clean))
    lines = ['<div class="toc"><h2>Contents</h2><ul>']
    for level, hid, text in items:
        cls = {1: "toc-h1", 2: "toc-h2", 3: "toc-h3"}[level]
        lines.append(f'<li class="{cls}"><a href="#{hid}">{text}</a></li>')
    lines.append("</ul></div>")
    return "\n".join(lines)


def build_cover(title, subtitle, student, course_num) -> str:
    today = datetime.date.today().strftime("%d %B %Y")
    eyebrow = f"IBM RAG &amp; AGENTIC AI PROFESSIONAL CERTIFICATE &middot; COURSE {course_num}" \
        if course_num else "COURSE NOTES"
    student_line = f"Compiled for {student}" if student else "Compiled notes"
    return f"""
    <div class="cover">
        <div class="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <div class="subtitle">{subtitle}</div>
        <div class="meta">{student_line} &middot; Edition of {today}</div>
    </div>
    """


def assemble(module_files, title, subtitle, student, course_num, work_dir, puppeteer_config) -> str:
    body_parts = []
    for f in module_files:
        text = Path(f).read_text(encoding="utf-8")
        body_parts.append(md_to_html_body(text, work_dir, puppeteer_config))
    merged_body = "\n<hr/>\n".join(body_parts)
    toc_html = build_toc(merged_body)
    cover_html = build_cover(title, subtitle, student, course_num)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
{cover_html}
{toc_html}
{merged_body}
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="Folder of module .md files (sorted by filename)")
    parser.add_argument("--output", required=True, help="Path for the merged PDF")
    parser.add_argument("--title", required=True)
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--student", default="")
    parser.add_argument("--course-num", default="")
    parser.add_argument("--css", default=str(Path(__file__).parent / "textbook.css"))
    parser.add_argument("--per-module", action="store_true",
                         help="Also emit one standalone PDF per module")
    parser.add_argument("--puppeteer-config", default=None,
                         help="Path to a puppeteer-config.json pointing mermaid-cli "
                              "at an already-installed browser (Chrome/Edge/Brave), "
                              "instead of relying on puppeteer's own Chrome download.")
    args = parser.parse_args()

    input_dir = Path(args.input)
    module_files = sorted(input_dir.glob("*.md"))
    if not module_files:
        sys.exit(f"No .md files found in {input_dir}")

    out_path = Path(args.output).resolve()
    work_dir = out_path.parent / "_diagram_cache"
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(module_files)} module file(s): {[f.name for f in module_files]}")

    # --- Merged textbook ---
    html_doc = assemble(module_files, args.title, args.subtitle,
                         args.student, args.course_num, work_dir, args.puppeteer_config)
    HTML(string=html_doc, base_url=str(work_dir)).write_pdf(
        str(out_path), stylesheets=[args.css]
    )
    print(f"✅ Wrote merged textbook: {out_path}")

    # --- Optional per-module PDFs ---
    if args.per_module:
        module_out_dir = out_path.parent / "modules_pdf"
        module_out_dir.mkdir(exist_ok=True)
        for f in module_files:
            single_html = assemble([f], f.stem.replace('_', ' ').title(),
                                    args.subtitle, args.student, args.course_num,
                                    work_dir, args.puppeteer_config)
            single_out = module_out_dir / (f.stem + ".pdf")
            HTML(string=single_html, base_url=str(work_dir)).write_pdf(
                str(single_out), stylesheets=[args.css]
            )
            print(f"✅ Wrote module PDF: {single_out}")


if __name__ == "__main__":
    main()