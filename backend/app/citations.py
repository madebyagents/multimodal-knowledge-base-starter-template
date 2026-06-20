"""Deterministic citation parsing and validation for grounded chat answers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_BRACKET_RE = re.compile(r"\[([^\[\]]{1,80})\]")
_LEADING_INT_RE = re.compile(r"^\s*(\d+)")
_ONLY_SOURCE_LIST_RE = re.compile(r"^\s*\d+(?:\s*,\s*\d+)*\s*$")


@dataclass(frozen=True)
class Citation:
    source_number: int
    raw: str


@dataclass(frozen=True)
class CitationValidation:
    source_count: int
    citations: list[Citation] = field(default_factory=list)
    invalid_source_numbers: list[int] = field(default_factory=list)
    missing_citations: bool = False

    @property
    def ok(self) -> bool:
        return not self.invalid_source_numbers and not self.missing_citations

    def to_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "source_count": self.source_count,
            "cited_source_numbers": sorted({c.source_number for c in self.citations}),
            "invalid_source_numbers": self.invalid_source_numbers,
            "missing_citations": self.missing_citations,
        }


def parse_citations(text: str) -> list[Citation]:
    """Parse DanteDash bracketed source references such as [1] or [3, p.12]."""
    citations: list[Citation] = []
    for match in _BRACKET_RE.finditer(text):
        raw_body = match.group(1).strip()
        raw = match.group(0)
        if _ONLY_SOURCE_LIST_RE.match(raw_body):
            citations.extend(Citation(int(number), raw) for number in raw_body.split(","))
            continue

        leading = _LEADING_INT_RE.match(raw_body)
        if leading:
            citations.append(Citation(int(leading.group(1)), raw))
    return citations


def validate_citations(
    text: str,
    *,
    source_count: int,
    require_citations: bool = True,
) -> CitationValidation:
    """Validate that every cited source number exists in the retrieved source set."""
    citations = parse_citations(text)
    invalid = sorted(
        {
            citation.source_number
            for citation in citations
            if citation.source_number < 1 or citation.source_number > source_count
        }
    )
    missing = require_citations and source_count > 0 and not citations
    return CitationValidation(
        source_count=source_count,
        citations=citations,
        invalid_source_numbers=invalid,
        missing_citations=missing,
    )
