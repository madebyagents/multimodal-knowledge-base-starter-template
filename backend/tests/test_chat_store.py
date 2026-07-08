from __future__ import annotations

import pytest

from app.chat_store import (
    DEFAULT_THREAD_TITLE,
    ChatStore,
    ChatStoreError,
    ChatStoreNotFound,
)


def make_store(tmp_path):
    return ChatStore(tmp_path / "chat.sqlite")


def test_chat_store_initializes_idempotently_and_creates_project(tmp_path) -> None:
    store = make_store(tmp_path)
    project = store.create_project(name="Cinema")

    ChatStore(tmp_path / "chat.sqlite")
    projects = store.list_projects()

    assert project["id"].startswith("proj_")
    assert projects[0]["name"] == "Cinema"
    assert projects[0]["thread_count"] == 0


def test_default_project_is_created_once(tmp_path) -> None:
    store = make_store(tmp_path)

    first = store.get_or_create_default_project()
    second = store.get_or_create_default_project()

    assert first["id"] == second["id"]
    assert len(store.list_projects()) == 1


def test_threads_messages_and_sources_round_trip_in_order(tmp_path) -> None:
    store = make_store(tmp_path)
    project = store.create_project(name="References")
    thread = store.create_thread(project_id=project["id"])

    user_msg = store.append_message(thread["id"], role="user", content="show me quiet pool light")
    assistant_msg = store.append_message(
        thread["id"],
        role="assistant",
        content="Use these two images [1].",
        chat_model="deepseek-v4-pro",
        top_k=5,
        visual_attachments=1,
        citation_validation={"ok": True, "source_count": 1},
    )
    store.save_message_sources(
        assistant_msg["id"],
        [
            {
                "node_id": "node-a",
                "file_id": "file-a",
                "score": 0.91,
                "modality": "image",
                "display_name": "A",
                "snippet": "pool",
                "preview_url": "/api/preview/file-a",
                "metadata": {"source_sha256": "abc", "dante_image_id": "shot-001"},
            }
        ],
    )

    detail = store.get_thread_detail(thread["id"])

    assert detail["title"] == "show me quiet pool light"
    assert [m["id"] for m in detail["messages"]] == [user_msg["id"], assistant_msg["id"]]
    assert detail["messages"][1]["citation_validation"] == {"ok": True, "source_count": 1}
    assert detail["messages"][1]["sources"][0]["payload"]["metadata"]["dante_image_id"] == "shot-001"


def test_thread_without_title_gets_safe_default_and_archived_threads_are_hidden(tmp_path) -> None:
    store = make_store(tmp_path)
    project = store.create_project()
    thread = store.create_thread(project_id=project["id"], title=" ")

    assert thread["title"] == DEFAULT_THREAD_TITLE
    assert store.list_threads(project["id"])[0]["id"] == thread["id"]

    store.update_thread(thread["id"], archived=True)

    assert store.list_threads(project["id"]) == []
    assert store.list_threads(project["id"], include_archived=True)[0]["id"] == thread["id"]


def test_missing_project_thread_and_invalid_role_are_controlled(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ChatStoreNotFound):
        store.get_project("missing")
    with pytest.raises(ChatStoreNotFound):
        store.get_thread("missing")

    project = store.create_project()
    thread = store.create_thread(project_id=project["id"])
    with pytest.raises(ChatStoreError, match="Unsupported message role"):
        store.append_message(thread["id"], role="system", content="nope")
