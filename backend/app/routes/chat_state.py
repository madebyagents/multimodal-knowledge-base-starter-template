"""Workspace project/thread state routes for persistent chat."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..chat_store import ChatStore, ChatStoreError, ChatStoreNotFound
from ..deps import get_chat_store
from ..schemas import (
    ProjectCreateRequest,
    ProjectDTO,
    ProjectUpdateRequest,
    ProjectsResponse,
    ThreadCreateRequest,
    ThreadDTO,
    ThreadDetailResponse,
    ThreadUpdateRequest,
    ThreadsResponse,
    WorkspaceBootstrapResponse,
    project_to_dto,
    thread_detail_to_dto,
    thread_to_dto,
)

router = APIRouter(tags=["chat-state"])
logger = logging.getLogger("kb.chat_state")


@router.post("/workspace/bootstrap", response_model=WorkspaceBootstrapResponse)
def bootstrap_workspace(
    store: ChatStore = Depends(get_chat_store),
) -> WorkspaceBootstrapResponse:
    project = store.get_or_create_default_project()
    threads = store.list_threads(project["id"])
    thread = threads[0] if threads else store.create_thread(project_id=project["id"])
    return WorkspaceBootstrapResponse(
        project=project_to_dto(project),
        thread=thread_to_dto(thread),
    )


@router.get("/projects", response_model=ProjectsResponse)
def list_projects(store: ChatStore = Depends(get_chat_store)) -> ProjectsResponse:
    return ProjectsResponse(projects=[project_to_dto(p) for p in store.list_projects()])


@router.post("/projects", response_model=ProjectDTO)
def create_project(
    req: ProjectCreateRequest,
    store: ChatStore = Depends(get_chat_store),
) -> ProjectDTO:
    return project_to_dto(store.create_project(name=req.name))


@router.get("/projects/{project_id}", response_model=ProjectDTO)
def get_project(
    project_id: str,
    store: ChatStore = Depends(get_chat_store),
) -> ProjectDTO:
    try:
        return project_to_dto(store.get_project(project_id))
    except ChatStoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/projects/{project_id}", response_model=ProjectDTO)
def update_project(
    project_id: str,
    req: ProjectUpdateRequest,
    store: ChatStore = Depends(get_chat_store),
) -> ProjectDTO:
    try:
        return project_to_dto(
            store.update_project(
                project_id,
                name=req.name,
                memory=req.memory,
                instructions=req.instructions,
            )
        )
    except ChatStoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/threads", response_model=ThreadsResponse)
def list_threads(
    project_id: str,
    include_archived: Annotated[bool, Query()] = False,
    store: ChatStore = Depends(get_chat_store),
) -> ThreadsResponse:
    try:
        threads = store.list_threads(project_id, include_archived=include_archived)
    except ChatStoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ThreadsResponse(threads=[thread_to_dto(t) for t in threads])


@router.post("/threads", response_model=ThreadDTO)
def create_thread(
    req: ThreadCreateRequest,
    store: ChatStore = Depends(get_chat_store),
) -> ThreadDTO:
    try:
        return thread_to_dto(
            store.create_thread(
                project_id=req.project_id,
                title=req.title,
                chat_model=req.chat_model,
                top_k=req.top_k,
            )
        )
    except ChatStoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/threads/{thread_id}", response_model=ThreadDetailResponse)
def get_thread(
    thread_id: str,
    store: ChatStore = Depends(get_chat_store),
) -> ThreadDetailResponse:
    try:
        return thread_detail_to_dto(store.get_thread_detail(thread_id))
    except ChatStoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/threads/{thread_id}", response_model=ThreadDTO)
def update_thread(
    thread_id: str,
    req: ThreadUpdateRequest,
    store: ChatStore = Depends(get_chat_store),
) -> ThreadDTO:
    try:
        return thread_to_dto(
            store.update_thread(
                thread_id,
                title=req.title,
                summary=req.summary,
                chat_model=req.chat_model,
                top_k=req.top_k,
                archived=req.archived,
                pinned=req.pinned,
            )
        )
    except ChatStoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatStoreError as exc:
        logger.warning("Thread update failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
