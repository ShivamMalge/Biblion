"""Tests for the parts that were silently wrong before.

Deliberately covers behaviour rather than implementation: binary discovery,
the fit heuristic, config precedence and diagram fallback markup.
"""

from pathlib import Path

import pytest

from biblion import cli, config, diagrams, document, tools


@pytest.fixture(autouse=True)
def _isolate_tools(tmp_path, monkeypatch):
    """Keep the test run out of the user's real ~/.biblion.

    Tool discovery is lru_cached, so a faked result would otherwise leak
    between tests, and constructing a renderer writes a puppeteer config.
    """
    monkeypatch.setattr(tools, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(tools, "BIN_DIR", tmp_path / "bin")
    tools.find_binary.cache_clear()
    tools.find_browser.cache_clear()
    yield
    tools.find_binary.cache_clear()
    tools.find_browser.cache_clear()


# --- binary discovery ------------------------------------------------------

def test_find_binary_sees_a_local_binary(tmp_path, monkeypatch):
    """The original bug: a d2 next to the project was invisible to which()."""
    monkeypatch.setattr(tools, "BIN_DIR", tmp_path / "nope")
    fake = tmp_path / ("d2.exe" if tools.IS_WINDOWS else "d2")
    fake.write_text("")
    tools.find_binary.cache_clear()
    found = tools.find_binary("d2", (str(tmp_path),))
    assert found is not None and found.name == fake.name


def test_find_binary_returns_absolute_paths(tmp_path, monkeypatch):
    """Windows CreateProcess will not resolve a bare relative name."""
    monkeypatch.chdir(tmp_path)
    fake = tmp_path / ("d2.exe" if tools.IS_WINDOWS else "d2")
    fake.write_text("")
    tools.find_binary.cache_clear()
    found = tools.find_binary("d2", (".",))
    assert found is not None and found.is_absolute()


def test_find_binary_missing_returns_none(tmp_path):
    tools.find_binary.cache_clear()
    assert tools.find_binary("definitely-not-a-real-binary", (str(tmp_path),)) is None


# --- browser discovery -----------------------------------------------------
#
# Biblion is developed on Windows, so the Linux and macOS branches would
# otherwise be exercised for the first time in CI. These simulate each
# platform by faking platform.system() and which files exist.

def _norm(path) -> str:
    """Compare paths the same way whichever OS runs the test.

    Path.as_posix() is not enough: it only rewrites separators on Windows, so
    a Windows candidate path keeps its backslashes when parsed as a PosixPath
    on Linux, and a POSIX candidate keeps its forward slashes on Windows.
    """
    return str(path).replace("\\", "/")


def _fake_platform(monkeypatch, system: str, existing: str | None):
    monkeypatch.delenv("BIBLION_BROWSER", raising=False)
    monkeypatch.setattr(tools.platform, "system", lambda: system)
    monkeypatch.setattr(Path, "is_file",
                        lambda self: _norm(self) == existing)
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    tools.find_browser.cache_clear()


def test_finds_chrome_on_linux(monkeypatch):
    _fake_platform(monkeypatch, "Linux", "/usr/bin/google-chrome")
    found = tools.find_browser()
    assert found is not None and _norm(found) == "/usr/bin/google-chrome"


def test_finds_chrome_on_macos(monkeypatch):
    path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    _fake_platform(monkeypatch, "Darwin", path)
    found = tools.find_browser()
    assert found is not None and _norm(found) == path


def test_finds_edge_on_windows(monkeypatch):
    path = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
    _fake_platform(monkeypatch, "Windows", path)
    found = tools.find_browser()
    assert found is not None and _norm(found) == path


def test_no_browser_returns_none(monkeypatch):
    _fake_platform(monkeypatch, "Linux", None)
    assert tools.find_browser() is None


# --- browser rasteriser ----------------------------------------------------

def test_rasteriser_rejects_an_svg_with_no_dimensions(tmp_path):
    svg = tmp_path / "bad.svg"
    svg.write_text("not really an svg", encoding="utf-8")
    ok, detail = tools.browser_svg_to_png(
        Path("no-such-browser"), svg, tmp_path / "out.png")
    assert not ok and "dimensions" in detail


def test_rasteriser_reports_a_missing_browser(tmp_path):
    svg = tmp_path / "ok.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>',
                   encoding="utf-8")
    ok, detail = tools.browser_svg_to_png(
        Path("definitely-not-a-browser"), svg, tmp_path / "out.png")
    assert not ok and detail


# --- fit heuristic ---------------------------------------------------------

def test_tall_layout_beats_wide_strip_for_a_long_chain():
    """A 1384x123 strip is less legible than a 300x1200 column."""
    assert diagrams.fit_scale(300, 1200) > diagrams.fit_scale(1384, 123)


def test_fit_scale_rejects_degenerate_sizes():
    assert diagrams.fit_scale(0, 100) == 0.0


def test_direction_rewrite_only_touches_the_direction():
    source = 'flowchart LR\n    A["Source code"] -->|build| B["Image"]'
    rewritten = diagrams.MERMAID_DIRECTION_RE.sub(r"\1TD", source, count=1)
    assert rewritten.startswith("flowchart TD")
    assert 'A["Source code"] -->|build| B["Image"]' in rewritten


def test_direction_rewrite_leaves_td_alone():
    source = "flowchart TD\n    A --> B"
    assert diagrams.MERMAID_DIRECTION_RE.sub(r"\1TD", source, count=1) == source


# --- d2 ---------------------------------------------------------------------

def test_d2_direction_is_turned_downward():
    source = "direction: right\n\na -> b: build\n"
    assert "direction: down" in diagrams._d2_downward(source)


def test_d2_sequence_diagrams_are_left_alone():
    """Sequence diagrams already read top-to-bottom; reshaping is wasted work."""
    source = "shape: sequence_diagram\ndirection: right\na -> b\n"
    assert diagrams._d2_downward(source) == source


def test_d2_nested_direction_is_not_rewritten():
    """Only a top-level declaration counts, not one inside a container."""
    source = "cluster: {\n  direction: right\n  a -> b\n}\n"
    assert diagrams._d2_downward(source) == source


def test_svg_dimensions_from_viewbox(tmp_path):
    svg = tmp_path / "a.svg"
    svg.write_text('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
                   'viewBox="0 0 296 455"><rect/></svg>', encoding="utf-8")
    assert tools.svg_dimensions(svg) == (296, 455)


def test_svg_dimensions_from_width_height(tmp_path):
    svg = tmp_path / "b.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" '
                   'width="120" height="60"></svg>', encoding="utf-8")
    assert tools.svg_dimensions(svg) == (120, 60)


def test_svg_dimensions_gives_up_cleanly(tmp_path):
    svg = tmp_path / "c.svg"
    svg.write_text("not an svg at all", encoding="utf-8")
    assert tools.svg_dimensions(svg) is None


# --- diagram fallback ------------------------------------------------------

class _NoToolRenderer(diagrams.DiagramRenderer):
    """A renderer with nothing installed, to exercise the failure path."""

    def __init__(self, cache_dir):
        super().__init__(cache_dir)
        self.mmdc = None
        self.d2 = None


def test_missing_renderer_produces_a_visible_failure(tmp_path):
    renderer = _NoToolRenderer(tmp_path)
    out = renderer.process('```mermaid\nflowchart LR\n  A --> B\n```')
    # Must not look like an ordinary code block, and must keep the source.
    assert "diagram-failed" in out
    assert "flowchart LR" in out
    assert not renderer.report.ok
    assert "mmdc" in renderer.report.skipped_missing_tool


def test_diagram_source_is_html_escaped(tmp_path):
    renderer = _NoToolRenderer(tmp_path)
    out = renderer.process('```d2\nx -> y\n```')
    assert "-&gt; y" in out
    assert "-> y" not in out


# --- document --------------------------------------------------------------

def test_title_comes_from_the_first_heading_not_the_filename():
    md = "# Containers and Containerization\n\nbody"
    assert document.title_from_markdown(md, "01_containers_docker") == \
        "Containers and Containerization"


def test_title_falls_back_when_there_is_no_heading():
    assert document.title_from_markdown("no heading", "fallback") == "fallback"


def test_toc_respects_depth():
    body = ('<h1 id="a">A</h1><h2 id="b">B</h2><h3 id="c">C</h3>')
    shallow = document.build_toc(body, max_depth=1)
    assert 'href="#a"' in shallow and 'href="#c"' not in shallow
    deep = document.build_toc(body, max_depth=3)
    assert 'href="#c"' in deep


def test_cover_has_no_hardcoded_branding():
    cover = document.build_cover("My Book")
    assert "IBM" not in cover
    assert "My Book" in cover


def test_cover_escapes_user_text():
    assert "&amp;" in document.build_cover("Docker & Kubernetes")


# --- config ----------------------------------------------------------------

def test_config_defaults_when_no_file(tmp_path):
    assert config.BookConfig.load(tmp_path).toc_depth == 3


def test_config_reads_toml(tmp_path):
    (tmp_path / "book.toml").write_text(
        'title = "T"\ntoc_depth = 1\n', encoding="utf-8")
    loaded = config.BookConfig.load(tmp_path)
    assert loaded.title == "T" and loaded.toc_depth == 1


def test_config_accepts_a_book_section(tmp_path):
    (tmp_path / "book.toml").write_text(
        '[book]\ntitle = "T"\n', encoding="utf-8")
    assert config.BookConfig.load(tmp_path).title == "T"


def test_config_rejects_typos(tmp_path):
    (tmp_path / "book.toml").write_text('titel = "T"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="titel"):
        config.BookConfig.load(tmp_path)


def test_cli_overrides_config_but_unset_flags_do_not(tmp_path):
    """argparse defaults must not silently clobber book.toml."""
    (tmp_path / "book.toml").write_text(
        'title = "From TOML"\ntoc_depth = 1\n', encoding="utf-8")

    class Args:
        title = "From CLI"
        toc_depth = None   # user did not pass it

    merged = config.BookConfig.load(tmp_path).merge_cli(Args())
    assert merged.title == "From CLI"
    assert merged.toc_depth == 1


def test_resolve_fills_in_output_and_title(tmp_path):
    (tmp_path / "modules").mkdir()
    resolved = config.BookConfig(input="modules").resolve(tmp_path)
    assert resolved.title == "Modules"
    assert resolved.output.endswith(".pdf")
    assert resolved.cache_dir


# --- packaging -------------------------------------------------------------

def test_repo_skill_matches_the_packaged_one():
    """The repo's .claude copy and the packaged copy must not drift apart."""
    root = Path(__file__).resolve().parent.parent
    packaged = root / "biblion" / "skill" / "SKILL.md"
    in_repo = root / ".claude" / "skills" / "biblion" / "SKILL.md"
    if not in_repo.is_file():          # a wheel install has only the packaged one
        pytest.skip("repo checkout not present")
    assert packaged.read_text(encoding="utf-8") == in_repo.read_text(encoding="utf-8")


def test_packaged_skill_has_frontmatter():
    root = Path(__file__).resolve().parent.parent
    text = (root / "biblion" / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "\nname: biblion\n" in text
    assert "\ndescription: " in text


# --- weasyprint diagnostics -------------------------------------------------

def test_macos_dylib_failure_suggests_the_loader_path(monkeypatch):
    """The macOS failure is a loader-path problem, not a missing pip package."""
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    hint = "\n".join(cli._weasyprint_hint(
        "cannot load library 'libgobject-2.0-0': dlopen(...)"))
    assert "DYLD_FALLBACK_LIBRARY_PATH" in hint
    assert "brew install pango" in hint


def test_linux_hint_names_the_apt_packages(monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    hint = "\n".join(cli._weasyprint_hint("cannot load library 'libgobject-2.0-0'"))
    assert "libpango" in hint
    assert "DYLD" not in hint


# --- figures ---------------------------------------------------------------

def test_caption_parsed_from_fence():
    assert diagrams.parse_caption('caption="A pipeline"') == "A pipeline"
    assert diagrams.parse_caption("caption='A pipeline'") == "A pipeline"
    assert diagrams.parse_caption("") == ""
    assert diagrams.parse_caption("someotherattr=1") == ""


def test_diagram_block_regex_separates_attrs_from_code():
    md = '```d2 caption="Hi"\na -> b\n```'
    match = diagrams.D2_BLOCK_RE.search(md)
    assert diagrams.parse_caption(match.group(1)) == "Hi"
    assert match.group(2) == "a -> b"


def test_plain_fence_still_parses():
    match = diagrams.MERMAID_BLOCK_RE.search("```mermaid\nflowchart TD\n  A --> B\n```")
    assert match.group(1).strip() == ""
    assert "flowchart TD" in match.group(2)


def test_figures_are_numbered_per_chapter():
    body = ('<h1 id="a">One</h1>'
            '<figure class="diagram"><img><figcaption>First</figcaption></figure>'
            '<figure class="diagram"><img><figcaption>Second</figcaption></figure>'
            '<h1 id="b">Two</h1>'
            '<figure class="diagram"><img><figcaption>Third</figcaption></figure>')
    out, entries = document.number_figures(body)
    assert "Figure 1.1" in out and "Figure 1.2" in out and "Figure 2.1" in out
    assert [e[0] for e in entries] == ["fig-1-1", "fig-1-2", "fig-2-1"]


def test_uncaptioned_figures_are_not_numbered():
    body = ('<h1 id="a">One</h1>'
            '<figure class="diagram"><img></figure>'
            '<figure class="diagram"><img><figcaption>Only me</figcaption></figure>')
    out, entries = document.number_figures(body)
    assert len(entries) == 1
    # The captioned one is still 1.1: the uncaptioned figure does not consume
    # a number.
    assert "Figure 1.1" in out
    assert entries[0][1].startswith("Figure 1.1")


def test_figure_list_links_to_ids():
    _, entries = document.number_figures(
        '<h1 id="a">C</h1><figure class="diagram">'
        '<img><figcaption>Cap</figcaption></figure>')
    listing = document.build_figure_list(entries)
    assert 'href="#fig-1-1"' in listing
    assert "Cap" in listing


def test_no_figure_list_when_there_are_no_figures():
    assert document.build_figure_list([]) == ""


# --- running headers -------------------------------------------------------
#
# These render a real PDF, so they need WeasyPrint's system libraries. The
# unit-test CI job deliberately does not install those; the book-building job
# does, and runs these for real.

class _NullRenderer:
    """A renderer that leaves markdown untouched, for layout-only tests."""

    def process(self, md_text):
        return md_text


def _render_pdf_or_skip(html_text, out_path):
    try:
        from weasyprint import HTML
    except Exception as exc:  # noqa: BLE001 - missing pango, not a test failure
        pytest.skip(f"weasyprint unavailable: {exc}")
    from biblion.cli import THEME_DIR
    HTML(string=html_text).write_pdf(
        str(out_path), stylesheets=[str(THEME_DIR / "textbook.css")])
    return pytest.importorskip("fitz").open(str(out_path))


def _header_bands(doc):
    """The text sitting in each page's top margin box."""
    bands = []
    for i in range(doc.page_count):
        height = doc[i].rect.height
        spans = [s["text"].strip()
                 for block in doc[i].get_text("dict")["blocks"]
                 for line in block.get("lines", [])
                 for s in line["spans"]
                 if s["bbox"][1] < height * 0.075]
        bands.append(" ".join(spans))
    return bands


def test_running_header_names_the_current_chapter(tmp_path):
    md = ("# Chapter One\n\n" + ("Filler sentence. " * 500)
          + "\n\n# Chapter Two\n\n" + ("Other text. " * 500))
    html = document.assemble([(Path("a.md"), md)], title="T",
                             renderer=_NullRenderer(), toc=False, cover=False,
                             figure_list=False)
    doc = _render_pdf_or_skip(html, tmp_path / "headers.pdf")
    bands = _header_bands(doc)
    assert any("Chapter One" in b for b in bands), bands
    assert any("Chapter Two" in b for b in bands), bands
    # The header must follow the chapter, not show One while inside Two.
    first_two = next(i for i, b in enumerate(bands) if "Chapter Two" in b)
    assert "Chapter One" not in bands[first_two]


def test_cover_page_has_no_running_header(tmp_path):
    md = "# Chapter One\n\n" + ("Filler. " * 300)
    html = document.assemble([(Path("a.md"), md)], title="The Book Title",
                             renderer=_NullRenderer(), toc=False, cover=True,
                             figure_list=False)
    doc = _render_pdf_or_skip(html, tmp_path / "cover.pdf")
    # The cover carries its own title as body text; what must not appear is a
    # running head, and the cover's <h1> must never become one.
    assert "Chapter One" not in _header_bands(doc)[0]


# --- themes ----------------------------------------------------------------
#
# Parametrised over whatever ships in themes/, so a theme added later is
# checked automatically rather than needing someone to remember.

def _theme_names():
    from biblion.cli import THEME_DIR
    return sorted(p.stem for p in THEME_DIR.glob("*.css"))


def _theme_css(name):
    from biblion.cli import THEME_DIR
    return (THEME_DIR / f"{name}.css").read_text(encoding="utf-8")


# Structural hooks the document generator emits. A theme missing one of these
# does not error -- it silently renders something ugly, which is worse.
REQUIRED_SELECTORS = [
    "@page", "@page :first", ".cover", ".cover .eyebrow", ".cover .subtitle",
    ".cover .meta", ".toc", ".figure-list",
    ".module h1", "string-set", ".codehilite", "table", "th", "td",
    ".admonition", ".admonition-title", ".diagram", "figcaption",
    ".figure-label", ".diagram-wide", ".diagram-failed",
    ".diagram-failed-label", "blockquote",
    # The contents page must resolve real page numbers. Which pseudo-element
    # carries them is the theme's business -- textbook uses ::before, report
    # uses ::after -- so require the mechanism, not one spelling of it.
    "target-counter",
]


@pytest.mark.parametrize("theme", _theme_names())
def test_theme_covers_every_structural_hook(theme):
    css = _theme_css(theme)
    missing = [sel for sel in REQUIRED_SELECTORS if sel not in css]
    assert not missing, f"{theme}.css is missing: {missing}"


@pytest.mark.parametrize("theme", _theme_names())
def test_theme_styles_every_callout_type(theme):
    css = _theme_css(theme)
    for kind in ("deepdive", "interview", "workhelp", "note", "tip"):
        assert f".admonition.{kind}" in css, f"{theme}.css does not style {kind}"


@pytest.mark.parametrize("theme", _theme_names())
def test_theme_renders_a_real_pdf(theme, tmp_path):
    """Each theme must actually produce a PDF with a working running header."""
    md = ("# Chapter One\n\n" + ("Body text. " * 300)
          + "\n\n## A section\n\n"
          + "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
          + "```python\nx = 1\n```\n\n"
          + '!!! note "Heads up"\n    Something worth knowing.\n\n'
          + "> A quotation.\n\n" + ("More body. " * 300))
    html = document.assemble([(Path("a.md"), md)], title="T",
                             renderer=_NullRenderer(), toc=True, cover=True,
                             figure_list=False)
    from biblion.cli import THEME_DIR
    try:
        from weasyprint import HTML
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"weasyprint unavailable: {exc}")
    out = tmp_path / f"{theme}.pdf"
    HTML(string=html).write_pdf(str(out), stylesheets=[str(THEME_DIR / f"{theme}.css")])
    doc = pytest.importorskip("fitz").open(str(out))
    assert doc.page_count >= 3
    assert any("Chapter One" in b for b in _header_bands(doc)[1:]), \
        f"{theme}: no running header"


def test_unknown_theme_lists_the_available_ones():
    from biblion.cli import theme_path
    with pytest.raises(SystemExit) as excinfo:
        theme_path("definitely-not-a-theme")
    message = str(excinfo.value)
    for name in _theme_names():
        assert name in message


# --- config errors ---------------------------------------------------------
#
# A typo in book.toml is user error. It must produce one clear line, never a
# Python traceback.

def _write_config(tmp_path, body):
    (tmp_path / "book.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_malformed_toml_is_a_clean_error(tmp_path):
    _write_config(tmp_path, 'title = "unterminated\n')
    with pytest.raises(config.ConfigError) as excinfo:
        config.BookConfig.load(tmp_path)
    assert "not valid TOML" in str(excinfo.value)


def test_wrong_type_names_the_setting_and_the_expected_type(tmp_path):
    _write_config(tmp_path, 'title = "T"\ntoc_depth = "three"\n')
    with pytest.raises(config.ConfigError) as excinfo:
        config.BookConfig.load(tmp_path)
    message = str(excinfo.value)
    assert "toc_depth" in message
    assert "whole number" in message


def test_wrong_bool_type_is_rejected(tmp_path):
    _write_config(tmp_path, 'title = "T"\ntoc = "yes"\n')
    with pytest.raises(config.ConfigError) as excinfo:
        config.BookConfig.load(tmp_path)
    assert "true or false" in str(excinfo.value)


def test_correct_types_are_accepted(tmp_path):
    _write_config(tmp_path, 'title = "T"\ntoc_depth = 2\ntoc = false\n')
    loaded = config.BookConfig.load(tmp_path)
    assert loaded.toc_depth == 2 and loaded.toc is False


def test_config_error_is_a_value_error():
    """Subclassing ValueError keeps older callers working."""
    assert issubclass(config.ConfigError, ValueError)
