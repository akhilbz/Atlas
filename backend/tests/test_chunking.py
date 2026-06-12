"""
Unit tests for utils/chunking.py — hybrid sentence/structure-aware chunking.

No database, no HTTP — pure function tests.
"""

import pytest
import tiktoken

from app.utils.chunking import (
    TextChunk,
    chunk_text,
    count_tokens,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP_SENTENCES,
    _split_into_sections,
    _split_sentences,
)

_ENC = tiktoken.get_encoding("cl100k_base")


def _tokens(text: str) -> int:
    return len(_ENC.encode(text))


def _make_sentences(n: int) -> str:
    """Build plain prose with n distinct sentences (~15 tokens each)."""
    return " ".join(
        f"This is sentence number {i}, containing enough words to be meaningful."
        for i in range(n)
    )


def _make_markdown(sections: dict[str, str]) -> str:
    """Build a markdown document from {heading: body} pairs."""
    return "\n\n".join(f"# {h}\n\n{b}" for h, b in sections.items())


# ---------------------------------------------------------------------------
# TextChunk dataclass
# ---------------------------------------------------------------------------

def test_text_chunk_has_content_index_and_token_count():
    chunk = TextChunk(content="hello", chunk_index=0, token_count=1)
    assert chunk.content == "hello"
    assert chunk.chunk_index == 0
    assert chunk.token_count == 1


def test_text_chunk_section_defaults_to_empty_string():
    chunk = TextChunk(content="hello", chunk_index=0, token_count=1)
    assert chunk.section == ""


def test_text_chunk_section_can_be_set():
    chunk = TextChunk(content="hello", chunk_index=0, token_count=1, section="Methods")
    assert chunk.section == "Methods"


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------

def test_count_tokens_returns_int():
    assert isinstance(count_tokens("hello world"), int)


def test_count_tokens_empty_string():
    assert count_tokens("") == 0


def test_count_tokens_matches_tiktoken_directly():
    text = "The quick brown fox jumps over the lazy dog."
    assert count_tokens(text) == _tokens(text)


# ---------------------------------------------------------------------------
# chunk_text — basic structure
# ---------------------------------------------------------------------------

def test_returns_list():
    assert isinstance(chunk_text("Hello world."), list)


def test_each_element_is_text_chunk():
    for item in chunk_text("Hello world."):
        assert isinstance(item, TextChunk)


def test_empty_string_returns_empty_list():
    assert chunk_text("") == []


def test_whitespace_only_returns_empty_list():
    assert chunk_text("   \n\n\t  ") == []


def test_chunk_indices_are_sequential():
    chunks = chunk_text(_make_sentences(40), chunk_size=100, overlap_sentences=1)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_token_count_field_matches_actual_content():
    chunks = chunk_text(_make_sentences(40), chunk_size=100, overlap_sentences=1)
    for chunk in chunks:
        assert chunk.token_count == _tokens(chunk.content)


# ---------------------------------------------------------------------------
# chunk_text — size behaviour
# ---------------------------------------------------------------------------

def test_short_text_produces_single_chunk():
    chunks = chunk_text("One sentence only.", chunk_size=200)
    assert len(chunks) == 1


def test_single_chunk_contains_full_text():
    text = "One sentence only."
    chunks = chunk_text(text, chunk_size=200)
    assert chunks[0].content == text


def test_large_text_produces_multiple_chunks():
    chunks = chunk_text(_make_sentences(60), chunk_size=100, overlap_sentences=1)
    assert len(chunks) > 1


def test_no_chunk_exceeds_chunk_size_for_normal_sentences():
    chunks = chunk_text(_make_sentences(50), chunk_size=150, overlap_sentences=1)
    for chunk in chunks:
        assert chunk.token_count <= 150


def test_last_chunk_may_be_smaller_than_chunk_size():
    chunks = chunk_text(_make_sentences(10), chunk_size=200, overlap_sentences=1)
    assert chunks[-1].token_count <= 200


# ---------------------------------------------------------------------------
# chunk_text — sentence boundary preservation
# ---------------------------------------------------------------------------

def test_each_chunk_ends_at_a_sentence_boundary():
    """Chunks must end with .  !  or  ? — never mid-sentence."""
    chunks = chunk_text(_make_sentences(30), chunk_size=100, overlap_sentences=1)
    for chunk in chunks:
        assert chunk.content.rstrip()[-1] in ".!?"


def test_oversized_single_sentence_emitted_as_own_chunk():
    """A sentence longer than chunk_size is not dropped — it becomes its own chunk."""
    long_sentence = "word " * 600  # ~600 tokens, well over any chunk_size
    chunks = chunk_text(long_sentence.strip() + ".", chunk_size=100)
    assert len(chunks) >= 1
    # Combined content should contain the original words
    combined = " ".join(c.content for c in chunks)
    assert "word" in combined


# ---------------------------------------------------------------------------
# chunk_text — markdown section awareness
# ---------------------------------------------------------------------------

def test_plain_text_chunk_sections_are_empty_string():
    chunks = chunk_text("No headings. Just plain text here.")
    for chunk in chunks:
        assert chunk.section == ""


def test_markdown_heading_populates_section_field():
    text = "# Introduction\n\nThis is the introduction. It has two sentences."
    chunks = chunk_text(text)
    assert all(c.section == "Introduction" for c in chunks)


def test_chunks_do_not_cross_heading_boundaries():
    text = _make_markdown({
        "Background": _make_sentences(15),
        "Methodology": _make_sentences(15),
    })
    chunks = chunk_text(text, chunk_size=120, overlap_sentences=1)
    sections_seen = {c.section for c in chunks}
    assert "Background" in sections_seen
    assert "Methodology" in sections_seen
    for chunk in chunks:
        assert chunk.section in ("Background", "Methodology")


def test_content_before_first_heading_has_empty_section():
    text = "Preamble text here.\n\n# Introduction\n\nIntro body."
    chunks = chunk_text(text)
    preamble = [c for c in chunks if c.section == ""]
    assert len(preamble) >= 1
    assert "Preamble" in preamble[0].content


def test_multiple_heading_levels_are_captured():
    text = "## Background\n\nBackground text here.\n\n### Details\n\nDetail text here."
    chunks = chunk_text(text)
    sections = {c.section for c in chunks}
    assert "Background" in sections
    assert "Details" in sections


def test_section_chunks_are_labelled_across_multiple_sections():
    text = _make_markdown({
        "Alpha": _make_sentences(10),
        "Beta": _make_sentences(10),
        "Gamma": _make_sentences(10),
    })
    chunks = chunk_text(text, chunk_size=120, overlap_sentences=1)
    sections = {c.section for c in chunks}
    assert sections == {"Alpha", "Beta", "Gamma"}


# ---------------------------------------------------------------------------
# chunk_text — overlap behaviour
# ---------------------------------------------------------------------------

def test_overlap_zero_no_sentence_appears_twice():
    """With overlap_sentences=0 every sentence appears in exactly one chunk."""
    sentences_text = _make_sentences(20)
    chunks = chunk_text(sentences_text, chunk_size=100, overlap_sentences=0)
    all_sentences = _split_sentences(sentences_text)
    seen: set[str] = set()
    for chunk in chunks:
        for s in _split_sentences(chunk.content):
            assert s not in seen, f"Duplicate sentence: {s!r}"
            seen.add(s)
    assert seen == set(all_sentences)


def test_overlap_one_carries_last_sentence_into_next_chunk():
    chunks = chunk_text(_make_sentences(25), chunk_size=80, overlap_sentences=1)
    assert len(chunks) >= 2
    last_sentence_of_first = _split_sentences(chunks[0].content)[-1]
    assert last_sentence_of_first in chunks[1].content


# ---------------------------------------------------------------------------
# chunk_text — defaults
# ---------------------------------------------------------------------------

def test_default_parameters_produce_valid_chunks():
    chunks = chunk_text(_make_sentences(80))
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.token_count <= DEFAULT_CHUNK_SIZE
        assert isinstance(chunk.section, str)


# ---------------------------------------------------------------------------
# _split_into_sections (unit tests for the helper directly)
# ---------------------------------------------------------------------------

def test_split_no_headings_returns_single_section():
    sections = _split_into_sections("Plain text without any headings.")
    assert sections == [("", "Plain text without any headings.")]


def test_split_single_heading():
    text = "# Methods\n\nBody text here."
    sections = _split_into_sections(text)
    assert len(sections) == 1
    assert sections[0][0] == "Methods"
    assert "Body text" in sections[0][1]


def test_split_multiple_headings():
    text = "# One\n\nFirst.\n\n# Two\n\nSecond."
    sections = _split_into_sections(text)
    assert len(sections) == 2
    assert sections[0][0] == "One"
    assert sections[1][0] == "Two"


def test_split_preamble_before_first_heading():
    text = "Intro text.\n\n# Section\n\nBody."
    sections = _split_into_sections(text)
    assert sections[0] == ("", "Intro text.")
    assert sections[1][0] == "Section"


# ---------------------------------------------------------------------------
# _split_sentences (unit tests for the helper directly)
# ---------------------------------------------------------------------------

def test_split_sentences_basic():
    sentences = _split_sentences("First sentence. Second sentence. Third sentence.")
    assert len(sentences) == 3


def test_split_sentences_strips_whitespace():
    sentences = _split_sentences("  Hello.  World.  ")
    for s in sentences:
        assert s == s.strip()


def test_split_sentences_empty_string():
    assert _split_sentences("") == []


def test_split_sentences_single_sentence_no_split():
    sentences = _split_sentences("Just one sentence.")
    assert sentences == ["Just one sentence."]


# ---------------------------------------------------------------------------
# Edge cases — normalisation and structure gaps
# ---------------------------------------------------------------------------

def test_windows_line_endings_in_markdown_headings():
    """_normalise converts \\r\\n to \\n so heading regex matches on Windows files."""
    text = "# Introduction\r\n\r\nIntro content. More intro.\r\n\r\n# Methods\r\n\r\nMethods content."
    chunks = chunk_text(text)
    sections = {c.section for c in chunks}
    assert "Introduction" in sections
    assert "Methods" in sections


def test_heading_with_empty_body_is_skipped():
    """A heading immediately followed by another heading produces no chunks for the empty section."""
    text = "# Methods\n\n# Results\n\nResults content here. More results."
    chunks = chunk_text(text)
    sections = {c.section for c in chunks}
    assert "Methods" not in sections
    assert "Results" in sections


def test_text_without_sentence_ending_punctuation():
    """Text with no .!? is treated as a single sentence and returned as one chunk."""
    text = "No period at the end of this line"
    chunks = chunk_text(text, chunk_size=200)
    assert len(chunks) == 1
    assert chunks[0].content == text
