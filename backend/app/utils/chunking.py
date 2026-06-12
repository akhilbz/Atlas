import re
from dataclasses import dataclass, field

import tiktoken
import structlog

logger = structlog.get_logger()

_ENCODING_NAME = "cl100k_base"  # matches text-embedding-3-small and GPT-4

DEFAULT_CHUNK_SIZE = 500        # tokens
DEFAULT_OVERLAP_SENTENCES = 1   # sentences carried into the next chunk

# Matches markdown headings at any level: # Title, ## Sub, ### Sub-sub, etc.
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)

# Splits on whitespace that follows sentence-ending punctuation.
# Known limitation: abbreviations ("Dr. Smith", "e.g. this") and numbered list
# markers ("1. item") are treated as sentence boundaries because the regex only
# looks at the preceding character, not context. In practice this is harmless —
# the orphaned fragment ("Dr.", "1.") lands in the same 500-token chunk as the
# rest of the sentence. Fixing this properly requires a full NLP tokeniser
# (spaCy) which is out of scope for Phase 2.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class TextChunk:
    """A single chunk of text ready for embedding."""

    content: str
    chunk_index: int
    token_count: int
    section: str = field(default="")  # heading this chunk falls under, "" if none


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_sentences: int = DEFAULT_OVERLAP_SENTENCES,
) -> list[TextChunk]:
    """Split text into semantically coherent chunks.

    Strategy:
    1. Split on markdown headings when present — chunks never cross section boundaries.
    2. Within each section, detect sentence boundaries.
    3. Group sentences greedily up to chunk_size tokens.
    4. Carry the last overlap_sentences sentences into the next chunk for context.

    Returns an empty list for blank input.
    """
    text = _normalise(text)
    if not text:
        return []

    enc = tiktoken.get_encoding(_ENCODING_NAME)
    sections = _split_into_sections(text)

    all_chunks: list[TextChunk] = []
    for heading, body in sections:
        sentences = _split_sentences(body)
        section_chunks = _group_sentences(
            sentences=sentences,
            chunk_size=chunk_size,
            overlap_sentences=overlap_sentences,
            section=heading,
            start_index=len(all_chunks),
            enc=enc,
        )
        all_chunks.extend(section_chunks)

    logger.debug(
        "text_chunked",
        num_chunks=len(all_chunks),
        chunk_size=chunk_size,
        overlap_sentences=overlap_sentences,
    )
    return all_chunks


def count_tokens(text: str) -> int:
    """Return the number of tokens in text using the cl100k_base encoding."""
    enc = tiktoken.get_encoding(_ENCODING_NAME)
    return len(enc.encode(text))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Strip and normalise line endings."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) pairs split on markdown headings.

    Content before the first heading is returned with heading="".
    If no headings exist the whole text is returned as a single ("", text) pair.
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []

    pre = text[: matches[0].start()].strip()
    if pre:
        sections.append(("", pre))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((heading, body))

    return sections


def _split_sentences(text: str) -> list[str]:
    """Split a block of text into individual sentences."""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _group_sentences(
    sentences: list[str],
    chunk_size: int,
    overlap_sentences: int,
    section: str,
    start_index: int,
    enc: tiktoken.Encoding,
) -> list[TextChunk]:
    """Group sentences into chunks up to chunk_size tokens.

    Advances by (window_size - overlap_sentences) each iteration so adjacent
    chunks share the last overlap_sentences sentences for context continuity.
    An oversized single sentence is emitted as its own chunk rather than dropped.
    """
    if not sentences:
        return []

    chunks: list[TextChunk] = []
    i = 0
    chunk_index = start_index

    while i < len(sentences):
        window: list[str] = []
        token_total = 0
        j = i

        while j < len(sentences):
            t = len(enc.encode(sentences[j]))
            # Accept an oversized sentence alone rather than skipping it.
            if token_total + t > chunk_size and window:
                break
            window.append(sentences[j])
            token_total += t
            j += 1

        chunks.append(
            TextChunk(
                content=" ".join(window),
                chunk_index=chunk_index,
                token_count=token_total,
                section=section,
            )
        )
        chunk_index += 1

        # Always advance at least 1 to avoid infinite loops.
        advance = max(1, len(window) - overlap_sentences)
        i += advance

    return chunks
