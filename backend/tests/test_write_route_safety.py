from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.kb_backends import KbWriteDisabled
from app.routes.ingest import clear, ingest
from app.routes.library import delete_item


class KnowledgeHubModeGateway:
    mode = "knowledge_hub"

    def __init__(self) -> None:
        self.cleared = False
        self.deleted: list[str] = []

    def clear(self) -> None:
        self.cleared = True
        raise KbWriteDisabled("write_disabled")

    def delete_by_file_id(self, file_id: str) -> int:
        self.deleted.append(file_id)
        raise KbWriteDisabled("write_disabled")


@pytest.mark.anyio
async def test_ingest_is_disabled_before_file_mutation_in_knowledge_hub_mode() -> None:
    gateway = KnowledgeHubModeGateway()

    with pytest.raises(HTTPException) as exc:
        await ingest(files=[object()], kb=gateway)

    assert exc.value.status_code == 409
    assert gateway.cleared is False
    assert gateway.deleted == []


@pytest.mark.anyio
async def test_clear_returns_409_in_knowledge_hub_mode() -> None:
    gateway = KnowledgeHubModeGateway()

    with pytest.raises(HTTPException) as exc:
        await clear(kb=gateway)

    assert exc.value.status_code == 409
    assert gateway.cleared is True


def test_delete_returns_409_in_knowledge_hub_mode() -> None:
    gateway = KnowledgeHubModeGateway()

    with pytest.raises(HTTPException) as exc:
        delete_item("file-a", kb=gateway)

    assert exc.value.status_code == 409
    assert gateway.deleted == ["file-a"]
