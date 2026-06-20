"""Cloud model providers for the Dante multimodal RAG sidecar."""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("kb.providers")


class ProviderError(RuntimeError):
    """Raised when a cloud provider returns an unusable response."""


@dataclass
class VoyageMultimodalEmbedder:
    """Thin REST client for Voyage multimodal embeddings."""

    api_key: str
    model: str = "voyage-multimodal-3.5"
    dimension: int = 1024
    endpoint: str = "https://api.voyageai.com/v1/multimodalembeddings"
    timeout_s: float = 120.0

    def embed_text(self, text: str, *, input_type: str) -> list[float]:
        return self._embed(
            [{"type": "text", "text": text}],
            input_type=input_type,
        )

    def embed_bytes(self, data: bytes, mime_type: str, *, input_type: str) -> list[float]:
        return self.embed_many_bytes([(data, mime_type)], input_type=input_type)[0]

    def embed_many_bytes(self, items: list[tuple[bytes, str]], *, input_type: str) -> list[list[float]]:
        if not items:
            return []
        inputs: list[dict[str, Any]] = []
        for data, mime_type in items:
            inputs.append({"content": [self._content_part(data, mime_type)]})
        return self._embed_many(inputs, input_type=input_type)

    def _content_part(self, data: bytes, mime_type: str) -> dict[str, str]:
        if mime_type.startswith("image/"):
            key = "image_base64"
        elif mime_type == "video/mp4":
            key = "video_base64"
        else:
            raise ProviderError(f"Voyage multimodal does not support MIME type {mime_type!r}")
        encoded = base64.b64encode(data).decode("ascii")
        return {"type": key, key: f"data:{mime_type};base64,{encoded}"}

    def _embed(self, content: list[dict[str, Any]], *, input_type: str) -> list[float]:
        return self._embed_many([{"content": content}], input_type=input_type)[0]

    def _embed_many(self, inputs: list[dict[str, Any]], *, input_type: str) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "inputs": inputs,
            "input_type": input_type,
        }
        # voyage-multimodal-3.5 defaults to 1024 dimensions. Keep the default
        # request clean, but allow explicit Matryoshka dimensions later.
        if self.dimension != 1024:
            payload["output_dimension"] = self.dimension

        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise ProviderError(f"Voyage embeddings HTTP {response.status_code}: {response.text[:500]}")

        body = response.json()
        data = body.get("data")
        if not isinstance(data, list) or len(data) != len(inputs):
            raise ProviderError(
                f"Voyage embeddings returned {0 if not isinstance(data, list) else len(data)} rows, "
                f"expected {len(inputs)}"
            )
        embeddings: list[list[float]] = []
        for index, row in enumerate(data):
            try:
                vec = row["embedding"]
            except (KeyError, TypeError) as exc:
                raise ProviderError(f"Voyage embeddings response did not include data[{index}].embedding") from exc
            if len(vec) != self.dimension:
                raise ProviderError(
                    f"Voyage embeddings returned {len(vec)} dimensions, expected {self.dimension}"
                )
            embeddings.append([float(v) for v in vec])
        return embeddings


@dataclass
class CohereReranker:
    """Cohere v2 rerank client for text queries over retrieved result cards."""

    api_key: str
    model: str = "rerank-v4.0-pro"
    endpoint: str = "https://api.cohere.com/v2/rerank"
    timeout_s: float = 60.0

    def rerank(
        self,
        query: str,
        items: list[Any],
        *,
        top_k: int,
        to_document: Callable[[Any], str],
    ) -> list[Any]:
        if not items:
            return []
        documents = [to_document(item) for item in items]
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": min(top_k, len(documents)),
            },
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise ProviderError(f"Cohere rerank HTTP {response.status_code}: {response.text[:500]}")

        ranked = []
        for row in response.json().get("results", []):
            idx = row.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(items):
                continue
            item = items[idx]
            relevance = row.get("relevance_score")
            if relevance is not None and hasattr(item, "metadata"):
                item.metadata["vector_score"] = item.score
                item.metadata["rerank_score"] = float(relevance)
                item.score = float(relevance)
            ranked.append(item)
        return ranked or items[:top_k]


@dataclass
class DeepSeekChatClient:
    """OpenAI-compatible streaming chat client for DeepSeek."""

    api_key: str
    model: str = "deepseek-v4-pro"
    base_url: str = "https://api.deepseek.com"
    timeout_s: float = 180.0

    def complete_chat(self, messages: list[dict[str, str]]) -> str:
        return "".join(self.stream_chat(messages))

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        with httpx.stream(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "stream": True,
                "temperature": 0.2,
            },
            timeout=self.timeout_s,
        ) as response:
            if response.status_code >= 400:
                text = response.read().decode("utf-8", errors="replace")
                raise ProviderError(f"DeepSeek chat HTTP {response.status_code}: {text[:500]}")

            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    logger.debug("Skipping malformed SSE data from DeepSeek: %r", data[:200])
                    continue
                delta = payload.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content")
                if token:
                    yield token


@dataclass
class CodexOAuthChatClient:
    """Non-streaming chat client backed by the local Codex OAuth session."""

    codex_bin: str = "codex"
    model: str = "gpt-5.5"
    reasoning_effort: str = "xhigh"
    timeout_s: float = 600.0

    def complete_chat(self, messages: list[dict[str, str]]) -> str:
        return "".join(self.stream_chat(messages))

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        prompt = _codex_prompt_from_messages(messages)
        with tempfile.TemporaryDirectory(prefix="dantedash_codex_chat_") as tmp:
            out_path = Path(tmp) / "answer.txt"
            cmd = [
                self.codex_bin,
                "exec",
                "--ignore-user-config",
                "--ephemeral",
                "-m",
                self.model,
                "-c",
                f"model_reasoning_effort={self.reasoning_effort}",
                "-s",
                "read-only",
                "-c",
                "approval_policy=never",
                "--skip-git-repo-check",
                "-C",
                tmp,
                "-o",
                str(out_path),
                prompt,
            ]
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_codex_oauth_env(),
                text=True,
                timeout=self.timeout_s,
            )
            if proc.returncode != 0:
                raise ProviderError(
                    f"Codex OAuth chat failed rc={proc.returncode}: {proc.stderr[-500:]}"
                )
            if not out_path.exists():
                raise ProviderError(
                    f"Codex OAuth chat produced no output: {proc.stderr[-500:]}"
                )
            answer = out_path.read_text(encoding="utf-8").strip()

        if not answer:
            raise ProviderError("Codex OAuth chat returned an empty answer.")
        yield answer


@dataclass
class ClaudeOAuthChatClient:
    """Non-streaming chat client backed by the local Claude OAuth session."""

    claude_bin: str = "claude"
    model: str = "claude-sonnet-4-6"
    effort: str = "medium"
    timeout_s: float = 900.0

    def complete_chat(self, messages: list[dict[str, str]]) -> str:
        return "".join(self.stream_chat(messages))

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        system_prompt, prompt = _claude_prompt_from_messages(messages)
        cmd = [
            self.claude_bin,
            "--print",
            "--model",
            self.model,
            "--effort",
            _claude_cli_effort(self.effort),
            "--system-prompt",
            system_prompt,
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            prompt,
        ]
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_claude_oauth_env(),
            text=True,
            timeout=self.timeout_s,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout)[-500:]
            raise ProviderError(
                f"Claude OAuth chat failed for {self.model} rc={proc.returncode}: {detail}"
            )
        answer = proc.stdout.strip()
        if not answer:
            raise ProviderError(f"Claude OAuth chat returned an empty answer for {self.model}.")
        yield answer


def _codex_prompt_from_messages(messages: list[dict[str, str]]) -> str:
    parts = [
        "Complete one grounded Dante Dashboard chat response.",
        "Use the message transcript below as the full context.",
        "Return only the assistant answer text. Do not expose implementation details, tool logs, or hidden reasoning.",
    ]
    for message in messages:
        role = message.get("role", "user").upper()
        content = message.get("content", "")
        parts.append(f"\n<{role}>\n{content}\n</{role}>")
    return "\n".join(parts)


def _claude_prompt_from_messages(messages: list[dict[str, str]]) -> tuple[str, str]:
    system_parts: list[str] = []
    prompt_parts = [
        "Complete one grounded Dante Dashboard chat response.",
        "Use the message transcript below as the full context.",
        "Return only the requested output. Do not expose implementation details, tool logs, or hidden reasoning.",
    ]
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
            continue
        tag = role.upper()
        prompt_parts.append(f"\n<{tag}>\n{content}\n</{tag}>")
    system_prompt = "\n\n".join(system_parts).strip() or (
        "Return only the assistant answer text. Do not expose implementation details."
    )
    return system_prompt, "\n".join(prompt_parts)


def _codex_oauth_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
    ):
        env.pop(key, None)
    return env


def _claude_oauth_env() -> dict[str, str]:
    env = dict(os.environ)
    home = str(Path.home())
    env.setdefault("HOME", home)
    env.setdefault("USER", Path(home).name)
    env.setdefault("LOGNAME", Path(home).name)
    env["PATH"] = (
        f"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{home}/.local/bin:"
        f"{env.get('PATH', '')}"
    )
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
    ):
        env.pop(key, None)
    return env


def _claude_cli_effort(effort: str) -> str:
    # Claude Code 2.1.178 exposes high/max, not xhigh. The Claude.ai OAuth
    # subscriber path rejects max, so xhigh maps to high for this transport.
    return "high" if effort == "xhigh" else effort
