from __future__ import annotations

from app.chat_models import CHAT_MODEL_CODEX_OAUTH
from app.kb import PipelineEvent, SearchResult
from app.rag import GroundedAnswer, answer_with_vision


class FakeChatClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] | None = None

    def stream_chat(self, messages: list[dict[str, str]]):
        self.messages = messages
        yield "The dashboard is grounded in retrieved evidence [1]."


class FakeKb:
    def __init__(self) -> None:
        self.client = FakeChatClient()

    def search_text(self, *args, **kwargs):
        on_progress = kwargs.get("on_progress")
        if on_progress:
            on_progress(PipelineEvent("search", "fake"))
        return [
            SearchResult(
                node_id="node-1",
                score=0.91,
                modality="text",
                metadata={"id": "file-1", "original_name": "note.md", "modality": "text"},
                snippet="The dashboard is grounded in retrieved evidence.",
            )
        ]

    def chat_client_for_model(self, chat_model):
        assert chat_model == CHAT_MODEL_CODEX_OAUTH
        return self.client


def test_answer_with_vision_uses_runtime_prompt_and_citation_validation() -> None:
    kb = FakeKb()
    chunks = list(answer_with_vision(kb, "What is grounded?", chat_model=CHAT_MODEL_CODEX_OAUTH))
    final = chunks[-1]
    assert isinstance(final, GroundedAnswer)
    assert final.citation_validation is not None
    assert final.citation_validation.ok
    assert kb.client.messages is not None
    assert "Provider Isolation" in kb.client.messages[0]["content"]
    assert "Grounding and Citation" in kb.client.messages[0]["content"]
