"""Tests for outbound text helpers."""

from __future__ import annotations

from clawcodex_ext.services.im_gateway.text import (
    DEFAULT_MAX_CHUNKS,
    maybe_truncate_with_liveview,
    split_text,
    strip_markdown,
)


def test_strip_markdown_removes_code_fence_and_bold() -> None:
    src = "## Title\n\n**bold** and _italic_ and `code`.\n\n```python\nprint(1)\n```"
    out = strip_markdown(src)
    assert "##" not in out
    assert "**" not in out
    assert "_" not in out
    assert "`" not in out
    assert "print(1)" in out
    assert "Title" in out


def test_strip_markdown_links_to_text() -> None:
    src = "see [docs](https://example.com/x) and ![alt](https://example.com/i.png)"
    out = strip_markdown(src)
    assert "docs" in out
    assert "alt" in out
    assert "https://example.com" not in out


def test_strip_markdown_list_markers() -> None:
    src = "- one\n- two\n1. first\n2. second\n> quote"
    out = strip_markdown(src)
    assert out.startswith("one")
    assert "first" in out
    assert "quote" in out
    assert "- " not in out


def test_split_text_short() -> None:
    assert split_text("hello", 4000) == ["hello"]


def test_split_text_long_on_boundary() -> None:
    text = "\n".join(f"line {i}" for i in range(1000))  # ~7000 chars
    chunks = split_text(text, 1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    # reconstruct loses only whitespace
    rejoined = " ".join(c.replace("\n", " ") for c in chunks)
    for i in range(1000):
        assert f"line {i}" in rejoined


def test_maybe_truncate_with_liveview_keeps_short() -> None:
    text = "x" * 100
    out = maybe_truncate_with_liveview(text, chunk_size=4000, max_chunks=4)
    assert out == [text]


def test_maybe_truncate_with_liveview_truncates_with_link() -> None:
    text = "\n".join(["word" * 200] * 40)  # very long
    out = maybe_truncate_with_liveview(
        text, chunk_size=4000, max_chunks=2, liveview_url="https://lv/x"
    )
    assert len(out) == 1
    assert "已截断" in out[0]
    assert "https://lv/x" in out[0]
