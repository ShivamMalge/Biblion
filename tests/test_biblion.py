"""Tests for the parts that were silently wrong before.

Deliberately covers behaviour rather than implementation: binary discovery,
the fit heuristic, config precedence and diagram fallback markup.
"""

from pathlib import Path

import pytest

from biblion import config, diagrams, document, tools


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
