"""Section segmenter for multi-schema documents.

Detects layout/format boundaries within a PDF and splits pages into
independent sections. Each section gets its own schema detection and
extraction pass.

Strategy:
- Compute per-page keyword profiles (bank_statement, custody, swift signals)
- Detect transitions where the dominant schema changes between consecutive pages
- Group consecutive pages with the same dominant schema into sections
- Also detect structural breaks: page headers changing, table format shifts
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from pipeline.models import PageOutput
from pipeline.schemas.router import (
    BANK_STATEMENT_KEYWORDS,
    CUSTODY_STATEMENT_KEYWORDS,
    SWIFT_CONFIRM_KEYWORDS,
)

logger = structlog.get_logger()


@dataclass
class DocumentSection:
    """A contiguous group of pages sharing the same layout/schema."""

    start_page: int  # 1-indexed
    end_page: int  # 1-indexed, inclusive
    page_outputs: list[PageOutput]
    dominant_schema: str  # "bank_statement", "custody_statement", "swift_confirm", "unknown"
    confidence: float = 0.0

    @property
    def num_pages(self) -> int:
        return self.end_page - self.start_page + 1


@dataclass
class PageProfile:
    """Keyword profile for a single page."""

    page_number: int
    bank_score: float = 0.0
    custody_score: float = 0.0
    swift_score: float = 0.0
    dominant_schema: str = "unknown"
    text_length: int = 0
    has_table: bool = False
    header_signature: str = ""  # first 100 chars for detecting header changes


def segment_document(page_outputs: list[PageOutput]) -> list[DocumentSection]:
    """Segment a document into sections based on layout/schema transitions.

    Analyzes each page's keyword profile and groups consecutive pages
    that share the same dominant schema. Transitions are detected when
    the dominant schema changes between pages.

    Args:
        page_outputs: Per-page extraction outputs in page order.

    Returns:
        List of DocumentSection objects, each representing a contiguous
        group of pages with consistent layout.
    """
    if not page_outputs:
        return []

    # If only one page, return a single section
    if len(page_outputs) == 1:
        profile = _compute_page_profile(page_outputs[0])
        return [
            DocumentSection(
                start_page=page_outputs[0].page_number,
                end_page=page_outputs[0].page_number,
                page_outputs=page_outputs,
                dominant_schema=profile.dominant_schema,
                confidence=max(profile.bank_score, profile.custody_score, profile.swift_score),
            )
        ]

    # Compute profiles for all pages
    profiles = [_compute_page_profile(po) for po in page_outputs]

    # Detect section boundaries
    sections: list[DocumentSection] = []
    current_start = 0

    for i in range(1, len(profiles)):
        if _is_section_boundary(profiles[i - 1], profiles[i]):
            # Close current section
            section_pages = page_outputs[current_start:i]
            section_schema = _resolve_section_schema(profiles[current_start:i])
            section_confidence = _section_confidence(profiles[current_start:i], section_schema)

            sections.append(
                DocumentSection(
                    start_page=page_outputs[current_start].page_number,
                    end_page=page_outputs[i - 1].page_number,
                    page_outputs=section_pages,
                    dominant_schema=section_schema,
                    confidence=section_confidence,
                )
            )
            current_start = i

    # Close final section
    section_pages = page_outputs[current_start:]
    section_schema = _resolve_section_schema(profiles[current_start:])
    section_confidence = _section_confidence(profiles[current_start:], section_schema)

    sections.append(
        DocumentSection(
            start_page=page_outputs[current_start].page_number,
            end_page=page_outputs[-1].page_number,
            page_outputs=section_pages,
            dominant_schema=section_schema,
            confidence=section_confidence,
        )
    )

    logger.info(
        "segmenter.complete",
        total_pages=len(page_outputs),
        sections_found=len(sections),
        section_schemas=[s.dominant_schema for s in sections],
        section_ranges=[(s.start_page, s.end_page) for s in sections],
    )

    return sections


def _compute_page_profile(page_output: PageOutput) -> PageProfile:
    """Compute keyword density profile for a single page."""
    # Build page text from text blocks and tokens
    text_parts: list[str] = []
    for block in page_output.text_blocks:
        text = block.get("text", "")
        if text:
            text_parts.append(str(text))

    if not text_parts:
        text_parts = [t.text for t in page_output.tokens]

    full_text = " ".join(text_parts).lower()
    word_count = max(len(full_text.split()), 1)

    # Compute scores
    bank_score = _keyword_score(full_text, BANK_STATEMENT_KEYWORDS, word_count)
    custody_score = _keyword_score(full_text, CUSTODY_STATEMENT_KEYWORDS, word_count)
    swift_score = _keyword_score(full_text, SWIFT_CONFIRM_KEYWORDS, word_count)

    # Determine dominant schema for this page
    scores = {
        "bank_statement": bank_score,
        "custody_statement": custody_score,
        "swift_confirm": swift_score,
    }
    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    # Header signature: first 100 non-whitespace chars (for detecting format changes)
    header_sig = full_text[:200].strip()

    return PageProfile(
        page_number=page_output.page_number,
        bank_score=bank_score,
        custody_score=custody_score,
        swift_score=swift_score,
        dominant_schema=best_type if best_score > 0.005 else "unknown",
        text_length=len(full_text),
        has_table=len(page_output.tables) > 0,
        header_signature=header_sig,
    )


def _keyword_score(text: str, keywords: list[str], word_count: int) -> float:
    """Compute keyword density score."""
    if not text or word_count == 0:
        return 0.0

    matches = 0
    for keyword in keywords:
        if keyword in text:
            count = text.count(keyword)
            matches += min(count, 3)

    return matches / (len(keywords) * max(word_count / 100, 1))


def _is_section_boundary(prev: PageProfile, curr: PageProfile) -> bool:
    """Detect if there's a section boundary between two consecutive pages.

    A boundary is detected ONLY when there's a clear transition between
    two different *known* schema types (e.g., bank_statement → custody_statement).
    Pages classified as 'unknown' never trigger boundaries — they're typically
    blank pages, separator pages, or pages with too little text to classify.
    """
    # Never split on unknown pages
    if prev.dominant_schema == "unknown" or curr.dominant_schema == "unknown":
        return False

    # Only trigger on actual schema type change between two known types
    if prev.dominant_schema != curr.dominant_schema:
        # Both must have meaningful scores (not just noise)
        prev_max = max(prev.bank_score, prev.custody_score, prev.swift_score)
        curr_max = max(curr.bank_score, curr.custody_score, curr.swift_score)
        if prev_max > 0.02 and curr_max > 0.02:
            return True

    return False


def _header_similarity(sig1: str, sig2: str) -> float:
    """Compute simple word-overlap similarity between two header signatures."""
    words1 = set(sig1.split()[:20])
    words2 = set(sig2.split()[:20])

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union) if union else 0.0


def _resolve_section_schema(profiles: list[PageProfile]) -> str:
    """Determine the dominant schema for a section from its page profiles.

    Uses majority voting across pages, weighted by score magnitude.
    """
    if not profiles:
        return "unknown"

    schema_weights: dict[str, float] = {
        "bank_statement": 0.0,
        "custody_statement": 0.0,
        "swift_confirm": 0.0,
    }

    for p in profiles:
        schema_weights["bank_statement"] += p.bank_score
        schema_weights["custody_statement"] += p.custody_score
        schema_weights["swift_confirm"] += p.swift_score

    best = max(schema_weights, key=lambda k: schema_weights[k])
    if schema_weights[best] > 0.01:
        return best

    return "unknown"


def _section_confidence(profiles: list[PageProfile], schema: str) -> float:
    """Compute confidence for a section's schema assignment."""
    if not profiles or schema == "unknown":
        return 0.0

    scores = []
    for p in profiles:
        if schema == "bank_statement":
            scores.append(p.bank_score)
        elif schema == "custody_statement":
            scores.append(p.custody_score)
        elif schema == "swift_confirm":
            scores.append(p.swift_score)

    return sum(scores) / len(scores) if scores else 0.0
