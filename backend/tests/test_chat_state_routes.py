from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.chat_store import ChatStore
from app.routes.chat_state import (
    bootstrap_workspace,
    create_thread,
    get_thread,
    list_threads,
    update_project,
    update_thread,
)
from app.schemas import ProjectUpdateRequest, ThreadCreateRequest, ThreadUpdateRequest


def make_store(tmp_path) -> ChatStore:
    return ChatStore(tmp_path / "chat.sqlite")


def test_bootstrap_creates_default_project_and_thread(tmp_path) -> None:
    store = make_store(tmp_path)

    response = bootstrap_workspace(store=store)

    assert response.project.name == "Dante"
    assert response.thread.project_id == response.project.id
    assert response.thread.title == "New chat"


def test_project_memory_update_is_explicit_and_scoped(tmp_path) -> None:
    store = make_store(tmp_path)
    project = store.create_project(name="Project A")
    other = store.create_project(name="Project B")

    response = update_project(
        project["id"],
        ProjectUpdateRequest(memory="Prefers low-key references.", instructions="Cite sources."),
        store=store,
    )

    assert response.memory == "Prefers low-key references."
    assert response.instructions == "Cite sources."
    assert store.get_project(other["id"])["memory"] == ""


def test_thread_routes_create_list_detail_and_archive(tmp_path) -> None:
    store = make_store(tmp_path)
    project = store.create_project(name="Refs")

    created = create_thread(
        ThreadCreateRequest(project_id=project["id"], title="Pool scenes", top_k=8),
        store=store,
    )
    store.append_message(created.id, role="user", content="Find pool stills")

    listed = list_threads(project["id"], store=store)
    detail = get_thread(created.id, store=store)

    assert listed.threads[0].id == created.id
    assert detail.messages[0].content == "Find pool stills"

    archived = update_thread(
        created.id,
        ThreadUpdateRequest(archived=True),
        store=store,
    )
    assert archived.archived is True
    assert list_threads(project["id"], store=store).threads == []
    assert list_threads(project["id"], include_archived=True, store=store).threads[0].id == created.id


def test_missing_project_and_thread_return_404(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(HTTPException) as project_exc:
        list_threads("missing", store=store)
    assert project_exc.value.status_code == 404

    with pytest.raises(HTTPException) as thread_exc:
        get_thread("missing", store=store)
    assert thread_exc.value.status_code == 404
