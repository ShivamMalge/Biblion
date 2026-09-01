"""Biblion command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, document, tools
from .config import CONFIG_NAME, TEMPLATE, BookConfig
from .diagrams import DiagramRenderer

PACKAGE_DIR = Path(__file__).parent
THEME_DIR = PACKAGE_DIR / "themes"


def theme_path(name: str) -> Path:
    """Resolve a theme name (or an explicit .css path) to a stylesheet."""
    candidate = Path(name)
    if candidate.suffix == ".css" and candidate.is_file():
        return candidate.resolve()
    packaged = THEME_DIR / f"{name}.css"
    if packaged.is_file():
        return packaged
    available = ", ".join(sorted(p.stem for p in THEME_DIR.glob("*.css")))
    raise SystemExit(f"Unknown theme {name!r}. Available: {available}")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def cmd_build(args) -> int:
    from weasyprint import HTML  # imported late; it is slow to load

    base = Path(args.project or ".").resolve()
    config = BookConfig.load(base).merge_cli(args).resolve(base)

    input_dir = (base / config.input).resolve()
    if not input_dir.is_dir():
        raise SystemExit(f"Input folder does not exist: {input_dir}")

    module_files = sorted(input_dir.glob("*.md"))
    if not module_files:
        raise SystemExit(f"No .md files found in {input_dir}")

    stylesheet = theme_path(config.css or config.theme)
    out_path = Path(config.output)
    if not out_path.is_absolute():
        out_path = (base / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    renderer = DiagramRenderer(
        cache_dir=Path(config.cache_dir),
        # The project root is searched for binaries too, so a d2.exe dropped
        # next to the book just works.
        project_dirs=(str(base), str(Path.cwd())),
        puppeteer_config=config.puppeteer_config or None,
        theme=config.diagram_theme,
        width=config.diagram_width,
        background=config.diagram_background,
        allow_downloads=config.allow_downloads,
        autofit=config.autofit,
    )

    print(f"Biblion {__version__}")
    print(f"  input   {input_dir}  ({len(module_files)} file(s))")
    print(f"  theme   {stylesheet.name}")
    print(f"  output  {out_path}")

    sources = [(f, f.read_text(encoding="utf-8")) for f in module_files]

    html_doc = document.assemble(
        sources, title=config.title, subtitle=config.subtitle,
        author=config.author, eyebrow=config.eyebrow, renderer=renderer,
        toc=config.toc, toc_depth=config.toc_depth, cover=config.cover)

    HTML(string=html_doc, base_url=str(base)).write_pdf(
        str(out_path), stylesheets=[str(stylesheet)])
    print(f"  wrote   {out_path}")

    if config.per_module:
        module_dir = out_path.parent / "modules_pdf"
        module_dir.mkdir(exist_ok=True)
        for path, text in sources:
            single = document.assemble(
                [(path, text)],
                title=document.title_from_markdown(
                    text, path.stem.replace("_", " ").title()),
                subtitle=config.subtitle, author=config.author,
                eyebrow=config.eyebrow, renderer=renderer,
                toc=config.toc, toc_depth=config.toc_depth, cover=config.cover)
            single_out = module_dir / f"{path.stem}.pdf"
            HTML(string=single, base_url=str(base)).write_pdf(
                str(single_out), stylesheets=[str(stylesheet)])
            print(f"  wrote   {single_out}")

    # --- diagram report --------------------------------------------------
    report = renderer.report
    print(f"\nDiagrams: {report.summary()}")
    for name, reason in report.failed:
        print(f"  ! {name}: {reason}", file=sys.stderr)
    if report.skipped_missing_tool:
        print("  Run `biblion doctor` to see how to install the missing tools.",
              file=sys.stderr)

    if config.strict and not report.ok:
        print("\nFailing because --strict was set and some diagrams did not render.",
              file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    base = Path(args.project or ".").resolve()
    print(f"Biblion {__version__}\n")

    try:
        import weasyprint
        print(f"  [ok]   weasyprint      {weasyprint.__version__}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] weasyprint      {exc}")
        print("         pip install weasyprint  (Windows also needs the GTK3 runtime)")

    statuses = tools.survey((str(base), str(Path.cwd())))
    for status in statuses:
        if status.ok:
            version = f"  {status.version}" if status.version else ""
            print(f"  [ok]   {status.name:<15} {status.path}{version}")
        else:
            print(f"  [--]   {status.name:<15} not found")
            print(f"         needed for: {status.required_for}")
            print(f"         install:    {status.install_hint}")

    mermaid_ok = statuses[0].ok
    d2_ok = statuses[1].ok
    rsvg_ok = statuses[3].ok

    print()
    if mermaid_ok:
        print("  ```mermaid blocks will render.")
    else:
        print("  ```mermaid blocks will NOT render.")
    if d2_ok and rsvg_ok:
        print("  ```d2 blocks will render via rsvg-convert.")
    elif d2_ok:
        print("  ```d2 blocks need a one-time Chromium download by d2;")
        print("  run `biblion build --allow-downloads` once to accept it.")
    else:
        print("  ```d2 blocks will NOT render.")
    return 0


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    base = Path(args.project or ".").resolve()
    base.mkdir(parents=True, exist_ok=True)

    config_path = base / CONFIG_NAME
    if config_path.exists() and not args.force:
        raise SystemExit(f"{config_path} already exists (use --force to overwrite)")

    title = args.title or base.name.replace("_", " ").replace("-", " ").title()
    slug = "_".join("".join(c for c in title if c.isalnum() or c.isspace()).split())

    config_path.write_text(TEMPLATE.format(title=title, slug=slug or "book"),
                           encoding="utf-8")
    print(f"Wrote {config_path}")

    modules = base / "modules"
    modules.mkdir(exist_ok=True)
    sample = modules / "01_introduction.md"
    if not sample.exists():
        sample.write_text(SAMPLE_MODULE, encoding="utf-8")
        print(f"Wrote {sample}")

    print("\nNext:")
    print("  1. biblion prompt > PROMPT.md    # give this to your AI")
    print("  2. put its markdown in modules/")
    print("  3. biblion build")
    return 0


SAMPLE_MODULE = """# Introduction

Write ordinary markdown here. Biblion handles the typography.

## Callouts

!!! deepdive "Why this exists"
    Use admonitions for the boxed asides. Types: deepdive, interview,
    workhelp, note, tip.

## Diagrams

```mermaid
flowchart LR
    A["Plain markdown"] -->|biblion build| B["Typeset PDF"]
```
"""


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------

def cmd_prompt(args) -> int:
    text = (PACKAGE_DIR / "authoring_prompt.md").read_text(encoding="utf-8")
    sys.stdout.write(text)
    return 0


# ---------------------------------------------------------------------------

def _add_build_flags(parser: argparse.ArgumentParser) -> None:
    """Build options.

    Every default is None so config.merge_cli can tell "user passed this"
    apart from "argparse filled in a default", and book.toml keeps its value.
    """
    parser.add_argument("--input", help="Folder of .md files (default: modules)")
    parser.add_argument("--output", help="Path for the merged PDF")
    parser.add_argument("--title")
    parser.add_argument("--subtitle")
    parser.add_argument("--author")
    parser.add_argument("--eyebrow", help="Small uppercase line above the cover title")
    parser.add_argument("--theme", help="Named theme (default: textbook)")
    parser.add_argument("--css", help="Path to a custom stylesheet")
    parser.add_argument("--toc-depth", type=int, help="Deepest heading level in contents")
    parser.add_argument("--no-toc", dest="toc", action="store_const", const=False,
                        help="Omit the contents page")
    parser.add_argument("--no-cover", dest="cover", action="store_const", const=False,
                        help="Omit the cover page")
    parser.add_argument("--per-module", action="store_const", const=True,
                        help="Also emit one PDF per source file")
    parser.add_argument("--strict", action="store_const", const=True,
                        help="Exit non-zero if any diagram fails to render")
    parser.add_argument("--allow-downloads", action="store_const", const=True,
                        help="Let d2 fetch its Chromium for PNG export")
    parser.add_argument("--diagram-theme", help="d2 theme id (see `d2 themes`)")
    parser.add_argument("--diagram-width", type=int)
    parser.add_argument("--no-autofit", dest="autofit", action="store_const",
                        const=False,
                        help="Render diagrams exactly as authored, even if they "
                             "are too wide to read on the page")
    parser.add_argument("--puppeteer-config",
                        help="Explicit puppeteer config for mermaid-cli "
                             "(auto-generated from your installed browser otherwise)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="biblion",
        description="Turn plain markdown into a typeset PDF book.")
    parser.add_argument("--version", action="version", version=f"biblion {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", help="Build the PDF")
    p_build.add_argument("project", nargs="?", default=".",
                         help="Project folder containing book.toml (default: .)")
    _add_build_flags(p_build)
    p_build.set_defaults(func=cmd_build)

    p_doctor = sub.add_parser("doctor", help="Check that renderers are installed")
    p_doctor.add_argument("project", nargs="?", default=".")
    p_doctor.set_defaults(func=cmd_doctor)

    p_init = sub.add_parser("init", help="Scaffold a new book folder")
    p_init.add_argument("project", nargs="?", default=".")
    p_init.add_argument("--title")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_prompt = sub.add_parser(
        "prompt", help="Print the markdown contract to hand to an AI")
    p_prompt.set_defaults(func=cmd_prompt)

    return parser


def _use_utf8_output() -> None:
    """Stop a legacy Windows console from killing the process.

    A stock cmd.exe/PowerShell console is cp1252, so writing an em dash --
    which the authoring prompt, book titles and renderer error text all
    contain -- raises UnicodeEncodeError and takes the whole command down.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _use_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
