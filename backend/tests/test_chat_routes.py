from __future__ import annotations

from app.kb_backends import KbBackendUnavailable
from app.routes.chat import _stream
from app.schemas import ChatRequest


class FailingKb:
    def search_text(self, *_args, **_kwargs):
        raise KbBackendUnavailable("/Users/vidigal/private/token")


def test_chat_stream_redacts_kb_backend_errors() -> None:
    frames = list(_stream(FailingKb(), ChatRequest(question="x"), store=object()))
    payload = "".join(frames)

    assert "Knowledge base backend unavailable." in payload
    assert "/Users/vidigal/private" not in payload
    assert "token" not in payload
