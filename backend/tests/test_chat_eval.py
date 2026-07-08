from __future__ import annotations

from app.chat_eval import QUALITY_GATE, compare_model_scores, score_answer, score_voice


def test_score_answer_passes_quality_gate_for_grounded_answer() -> None:
    scores = score_answer(
        answer="DanteDash uses retrieved cards as grounded evidence [1].",
        source_count=1,
        source_panel_count=1,
    )
    assert scores.total >= QUALITY_GATE
    assert scores.passes_gate


def test_score_answer_fails_missing_citation() -> None:
    scores = score_answer(
        answer="DanteDash uses retrieved cards as grounded evidence.",
        source_count=1,
        source_panel_count=1,
    )
    assert scores.citation_validity_score == 0.0
    assert not scores.passes_gate


def test_score_answer_fails_cross_provider_path() -> None:
    scores = score_answer(
        answer="The answer is grounded [1].",
        source_count=1,
        source_panel_count=1,
        provider_isolated=False,
    )
    assert scores.provider_isolation_score == 0.0
    assert not scores.passes_gate


def test_compare_model_scores_reports_tie_and_winner() -> None:
    tie = compare_model_scores(
        model_a="deepseek-v4-pro",
        score_a=0.9,
        model_b="codex-gpt-5.5-oauth",
        score_b=0.9004,
    )
    assert tie.winner == "tie"

    winner = compare_model_scores(
        model_a="deepseek-v4-pro",
        score_a=0.8,
        model_b="codex-gpt-5.5-oauth",
        score_b=0.9,
    )
    assert winner.winner == "codex-gpt-5.5-oauth"
    assert winner.delta == 0.1


def test_score_voice_flags_dash_separators_and_ai_tells() -> None:
    scores = score_voice(
        "Great question. It's important to note that the dashboard is grounded — and concise [1]. "
        "This part uses an en dash – as a separator."
    )
    assert scores.em_dash_count == 1
    assert scores.en_dash_separator_count == 1
    assert scores.ai_tell_count == 2
    assert not scores.has_soft_warnings
    assert not scores.voice_clean


def test_score_voice_allows_clean_grounded_answer() -> None:
    scores = score_voice("The dashboard grounds answers in retrieved cards, then cites the card numbers [1].")
    assert scores.voice_clean
    assert not scores.has_soft_warnings


def test_score_voice_counts_over_apology_as_hard_ai_tell() -> None:
    scores = score_voice("I'm sorry, based on the provided sources, the answer is not covered [1].")
    assert scores.ai_tell_count == 2
    assert not scores.voice_clean


def test_score_voice_reports_soft_bullet_dump_and_throat_clearing() -> None:
    scores = score_voice(
        "Here is the answer.\n"
        "- One grounded point [1]\n"
        "- Another grounded point [1]\n"
        "- A third grounded point [1]\n"
        "- A fourth grounded point [1]\n"
    )
    assert scores.voice_clean
    assert scores.bullet_dump_count == 1
    assert scores.throat_clearing_count == 1
    assert scores.has_soft_warnings
