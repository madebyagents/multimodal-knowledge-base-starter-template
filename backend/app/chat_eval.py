"""Deterministic quality/reliability scoring for DanteDash chat evals."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .citations import CitationValidation, validate_citations

QUALITY_GATE = 0.78
AI_TELL_PATTERNS: tuple[str, ...] = (
    "it's important to note",
    "it is important to note",
    "furthermore",
    "moreover",
    "as an ai",
    "in conclusion",
    "i'd be happy to",
    "i would be happy to",
    "certainly!",
    "great question",
    "delve",
    "rest assured",
    "let's explore",
    "let us explore",
    "it should be noted",
    "notably,",
    "based on the provided sources",
    "based on the sources",
    "the provided cards",
    "i hope this helps",
    "in summary",
    "it's worth noting",
    "it is worth noting",
    "i apologize",
    "i'm sorry",
)
THROAT_CLEARING_PREFIXES: tuple[str, ...] = (
    "to answer your question",
    "here's",
    "here is",
    "let me",
    "i'll",
    "i will",
    "the following",
    "based on",
)


@dataclass(frozen=True)
class EvalScores:
    grounding_score: float
    citation_validity_score: float
    insufficiency_calibration_score: float
    source_panel_consistency_score: float
    provider_isolation_score: float
    worker_contract_score: float
    latency_reliability_score: float
    citation_validation: CitationValidation

    @property
    def total(self) -> float:
        return round(
            0.25 * self.grounding_score
            + 0.20 * self.citation_validity_score
            + 0.15 * self.insufficiency_calibration_score
            + 0.15 * self.source_panel_consistency_score
            + 0.10 * self.provider_isolation_score
            + 0.10 * self.worker_contract_score
            + 0.05 * self.latency_reliability_score,
            4,
        )

    @property
    def passes_gate(self) -> bool:
        hard_guards_pass = (
            self.citation_validity_score > 0
            and self.provider_isolation_score > 0
            and self.worker_contract_score > 0
        )
        return hard_guards_pass and self.total >= QUALITY_GATE

    def to_payload(self) -> dict[str, object]:
        return {
            "score": self.total,
            "passes_gate": self.passes_gate,
            "grounding_score": self.grounding_score,
            "citation_validity_score": self.citation_validity_score,
            "insufficiency_calibration_score": self.insufficiency_calibration_score,
            "source_panel_consistency_score": self.source_panel_consistency_score,
            "provider_isolation_score": self.provider_isolation_score,
            "worker_contract_score": self.worker_contract_score,
            "latency_reliability_score": self.latency_reliability_score,
            "citation_validation": self.citation_validation.to_payload(),
        }


@dataclass(frozen=True)
class VoiceScores:
    em_dash_count: int
    en_dash_separator_count: int
    ai_tell_count: int
    ai_tell_hits: tuple[str, ...]
    bullet_dump_count: int = 0
    throat_clearing_count: int = 0

    @property
    def voice_clean(self) -> bool:
        return self.em_dash_count == 0 and self.en_dash_separator_count == 0 and self.ai_tell_count == 0

    @property
    def has_soft_warnings(self) -> bool:
        return self.bullet_dump_count > 0 or self.throat_clearing_count > 0

    def to_payload(self) -> dict[str, object]:
        return {
            "em_dash_count": self.em_dash_count,
            "en_dash_separator_count": self.en_dash_separator_count,
            "ai_tell_count": self.ai_tell_count,
            "ai_tell_hits": list(self.ai_tell_hits),
            "bullet_dump_count": self.bullet_dump_count,
            "throat_clearing_count": self.throat_clearing_count,
            "has_soft_warnings": self.has_soft_warnings,
            "voice_clean": self.voice_clean,
        }


@dataclass(frozen=True)
class ModelComparison:
    model_a: str
    model_b: str
    score_a: float
    score_b: float
    winner: str
    delta: float

    def to_payload(self) -> dict[str, object]:
        return {
            "model_a": self.model_a,
            "model_b": self.model_b,
            "score_a": self.score_a,
            "score_b": self.score_b,
            "winner": self.winner,
            "delta": self.delta,
        }


def score_answer(
    *,
    answer: str,
    source_count: int,
    source_panel_count: int,
    expected_insufficient: bool = False,
    provider_isolated: bool = True,
    worker_contract_ok: bool = True,
    latency_ok: bool = True,
) -> EvalScores:
    citation_validation = validate_citations(
        answer,
        source_count=source_count,
        require_citations=not expected_insufficient,
    )
    citation_score = 1.0 if citation_validation.ok else 0.0
    grounding_score = 1.0 if citation_validation.citations and citation_validation.ok else 0.35
    if expected_insufficient:
        lowered = answer.lower()
        insufficiency_score = 1.0 if "not enough" in lowered or "does not cover" in lowered else 0.0
        grounding_score = max(grounding_score, 0.75)
    else:
        insufficiency_score = 1.0

    return EvalScores(
        grounding_score=grounding_score,
        citation_validity_score=citation_score,
        insufficiency_calibration_score=insufficiency_score,
        source_panel_consistency_score=1.0 if source_panel_count == source_count else 0.0,
        provider_isolation_score=1.0 if provider_isolated else 0.0,
        worker_contract_score=1.0 if worker_contract_ok else 0.0,
        latency_reliability_score=1.0 if latency_ok else 0.0,
        citation_validation=citation_validation,
    )


def score_voice(answer: str) -> VoiceScores:
    """Score deterministic voice hygiene for a user-facing answer."""
    lowered = answer.lower()
    hits = tuple(pattern for pattern in AI_TELL_PATTERNS if pattern in lowered)
    return VoiceScores(
        em_dash_count=answer.count("\u2014"),
        en_dash_separator_count=_en_dash_separator_count(answer),
        ai_tell_count=len(hits),
        ai_tell_hits=hits,
        bullet_dump_count=_bullet_dump_count(answer),
        throat_clearing_count=_throat_clearing_count(answer),
    )


def _en_dash_separator_count(answer: str) -> int:
    # Count en dashes used like sentence separators. Numeric ranges such as
    # 3-5 or page labels should not match because they lack spaces.
    return len(re.findall(r"\s\u2013\s", answer))


def _bullet_dump_count(answer: str) -> int:
    bullet_lines = re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+\S", answer)
    return 1 if len(bullet_lines) >= 4 else 0


def _throat_clearing_count(answer: str) -> int:
    first_sentence = re.split(r"(?<=[.!?])\s+", answer.strip(), maxsplit=1)[0].lower()
    return 1 if any(first_sentence.startswith(prefix) for prefix in THROAT_CLEARING_PREFIXES) else 0


def compare_model_scores(
    *,
    model_a: str,
    score_a: float,
    model_b: str,
    score_b: float,
    tie_epsilon: float = 0.001,
) -> ModelComparison:
    """Compare two model scores for deterministic A/B reporting."""
    delta = round(score_b - score_a, 4)
    if abs(delta) <= tie_epsilon:
        winner = "tie"
    elif delta > 0:
        winner = model_b
    else:
        winner = model_a
    return ModelComparison(
        model_a=model_a,
        model_b=model_b,
        score_a=score_a,
        score_b=score_b,
        winner=winner,
        delta=delta,
    )
