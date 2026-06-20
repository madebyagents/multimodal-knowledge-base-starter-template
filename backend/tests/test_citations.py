from __future__ import annotations

from app.citations import parse_citations, validate_citations


def test_parse_citations_handles_media_forms() -> None:
    citations = parse_citations("See page 4 [1, p.4] and the frame [2, 10:05-10:20].")
    assert [c.source_number for c in citations] == [1, 2]


def test_parse_citations_handles_adjacent_and_list_forms() -> None:
    citations = parse_citations("The point is supported [1][2] and repeated [3, 4].")
    assert [c.source_number for c in citations] == [1, 2, 3, 4]


def test_validate_citations_rejects_missing_source_number() -> None:
    validation = validate_citations("Unsupported citation [9].", source_count=2)
    assert not validation.ok
    assert validation.invalid_source_numbers == [9]


def test_validate_citations_can_require_at_least_one_citation() -> None:
    validation = validate_citations("No inline source here.", source_count=2)
    assert not validation.ok
    assert validation.missing_citations
