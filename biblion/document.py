"""Markdown -> HTML assembly: cover page, table of contents, body."""

from __future__ import annotations

import datetime
import html
import re
from pathlib import Path

import markdown

HEADING_RE = re.compile(r'<h([1-6])[^>]*\bid="([^"]+)"[^>]*>(.*?)</h\1>', re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
FIRST_H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)

MD_EXTENSIONS = [
    "extra",        # tables, fenced code, footnotes, def lists
    "admonition",   # !!! callout boxes
    "codehilite",   # syntax highlighting
    "toc",          # heading ids
    "sane_lists",
]

MD_EXTENSION_CONFIGS = {
    "codehilite": {"css_class": "codehilite", "guess_lang": False},
    "toc": {"anchorlink": False},
}


def markdown_to_html(md_text: str, renderer) -> str:
    """Render one markdown document to an HTML fragment.

    Diagram blocks are turned into <img> tags *before* the markdown pass, so
    the markdown parser never sees the diagram source.
    """
    md_text = renderer.process(md_text)
    return markdown.markdown(md_text, extensions=MD_EXTENSIONS,
                             extension_configs=MD_EXTENSION_CONFIGS)


def title_from_markdown(md_text: str, fallback: str) -> str:
    """The document's own first H1, which beats a title guessed from a filename.

    ``01_containers_docker_k8s_openshift`` prettifies to the fairly grim
    "01 Containers Docker K8S Openshift"; the file's actual heading is what
    the author wrote and is always better.
    """
    match = FIRST_H1_RE.search(md_text)
    if match:
        return match.group(1).strip()
    return fallback


def build_toc(html_body: str, max_depth: int = 3) -> str:
    """Build a linked contents list from the headings in the body."""
    items = []
    for level, heading_id, text in HEADING_RE.findall(html_body):
        level = int(level)
        if level > max_depth:
            continue
        clean = html.unescape(TAG_RE.sub("", text)).strip()
        if clean:
            items.append((level, heading_id, clean))

    if not items:
        return ""

    lines = ['<div class="toc"><h2>Contents</h2><ul>']
    for level, heading_id, text in items:
        lines.append(f'<li class="toc-h{level}">'
                     f'<a href="#{heading_id}">{html.escape(text)}</a></li>')
    lines.append("</ul></div>")
    return "\n".join(lines)


def build_cover(title: str, subtitle: str = "", author: str = "",
                eyebrow: str = "", date: str | None = None) -> str:
    """The cover page.

    Everything here is caller-supplied. The first version hardcoded an IBM
    certificate string as the default eyebrow, which made the tool unusable
    for anyone else's book.
    """
    stamp = date or datetime.date.today().strftime("%d %B %Y")

    parts = ['<div class="cover">']
    if eyebrow:
        parts.append(f'<div class="eyebrow">{html.escape(eyebrow)}</div>')
    parts.append(f'<h1>{html.escape(title)}</h1>')
    if subtitle:
        parts.append(f'<div class="subtitle">{html.escape(subtitle)}</div>')

    meta = " &middot; ".join(
        bit for bit in [html.escape(author) if author else "", stamp] if bit)
    parts.append(f'<div class="meta">{meta}</div>')
    parts.append("</div>")
    return "\n".join(parts)


def assemble(sources: list[tuple[Path, str]], *, title: str, subtitle: str = "",
             author: str = "", eyebrow: str = "", date: str | None = None,
             renderer, toc: bool = True, toc_depth: int = 3,
             cover: bool = True) -> str:
    """Build the full HTML document from a list of (path, markdown) pairs."""
    bodies = [markdown_to_html(text, renderer) for _, text in sources]
    merged = "\n".join(f'<section class="module">{body}</section>'
                       for body in bodies)

    head = []
    if cover:
        head.append(build_cover(title, subtitle, author, eyebrow, date))
    if toc:
        head.append(build_toc(merged, toc_depth))

    return (
        "<!DOCTYPE html>\n<html>\n<head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title></head>\n<body>\n"
        + "\n".join(head)
        + "\n" + merged + "\n</body>\n</html>"
    )
