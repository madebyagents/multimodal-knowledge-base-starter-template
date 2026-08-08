from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.chat_models import CHAT_MODEL_DEEPSEEK
from app.chat_store import ChatStore
from app.kb import SearchResult
from app.routes.chat import _stream, chat
from app.schemas import ChatRequest


class FakeChatClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def stream_chat(self, messages: list[dict[str, str]]):
        self.messages = messages
        yield "Answer from sources [1]."


class FakeKB:
    def __init__(self) -> None:
        self.client = FakeChatClient()

    def search_text(self, question, *, top_k, modality_filter, on_progress):
        self.search_call = {
            "question": question,
            "top_k": top_k,
            "modality_filter": modality_filter,
        }
        return [
            SearchResult(
                node_id="node-a",
                score=0.9,
                modality="image",
                metadata={
                    "id": "file-a",
                    "original_name": "Pool still",
                    "source_sha256": "sha-a",
                    "dante_image_id": "pool-001",
                },
                snippet="A still with quiet pool light.",
            )
        ]

    def chat_client_for_model(self, chat_model):
        assert chat_model == CHAT_MODEL_DEEPSEEK
        return self.client


def make_store(tmp_path) -> ChatStore:
    return ChatStore(tmp_path / "chat.sqlite")


def parse_sse_frames(frames: list[str]) -> list[tuple[str, object]]:
    parsed = []
    for frame in frames:
        event = "message"
        data = ""
        for line in frame.strip().splitlines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            if line.startswith("data: "):
                data = line.removeprefix("data: ")
        parsed.append((event, json.loads(data)))
    return parsed


def test_one_shot_chat_request_does_not_persist_messages(tmp_path) -> None:
    store = make_store(tmp_path)
    kb = FakeKB()

    frames = list(
        _stream(
            kb,
            ChatRequest(question="What is here?", chat_model=CHAT_MODEL_DEEPSEEK),
            store,
        )
    )

    assert parse_sse_frames(frames)[0] == ("message", "Answer from sources [1].")
    assert store.list_projects() == []


def test_thread_chat_persists_turn_sources_and_context(tmp_path) -> None:
    store = make_store(tmp_path)
    project = store.create_project(
        name="Cinema",
        memory="Prefer low-key, source-grounded visual references.",
    )
    thread = store.create_thread(project_id=project["id"], title="Pool references")
    store.append_message(thread["id"], role="user", content="Earlier question")
    store.append_message(thread["id"], role="assistant", content="Earlier answer [1].")
    kb = FakeKB()

    frames = list(
        _stream(
            kb,
            ChatRequest(
                question="Continue with this mood",
                top_k=8,
                chat_model=CHAT_MODEL_DEEPSEEK,
                project_id=project["id"],
                thread_id=thread["id"],
            ),
            store,
        )
    )

    parsed = parse_sse_frames(frames)
    sources_event = next(data for event, data in parsed if event == "sources")
    detail = store.get_thread_detail(thread["id"])

    assert sources_event["sources"][0]["metadata"]["dante_image_id"] == "pool-001"
    assert [m["role"] for m in detail["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert detail["messages"][-1]["sources"][0]["payload"]["node_id"] == "node-a"
    assert detail["top_k"] == 8
    prompt = kb.client.messages[-1]["content"]
    assert "Curated project memory" in prompt
    assert "Earlier answer" in prompt
    assert "Retrieved sources" in prompt


def test_chat_rejects_thread_project_mismatch(tmp_path) -> None:
    store = make_store(tmp_path)
    project = store.create_project(name="A")
    other = store.create_project(name="B")
    thread = store.create_thread(project_id=project["id"])

    with pytest.raises(HTTPException) as exc:
        chat(
            ChatRequest(
                question="What?",
                project_id=other["id"],
                thread_id=thread["id"],
            ),
            kb=FakeKB(),
            store=store,
        )

    assert exc.value.status_code == 400
