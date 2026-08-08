"""Markdown prompt asset loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptAsset:
    path: Path
    metadata: dict[str, str]
    body: str


def load_prompt_asset(path: Path) -> PromptAsset:
    text = path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        try:
            _, raw_meta, body = text.split("---\n", 2)
        except ValueError as exc:
            raise ValueError(f"Invalid prompt frontmatter: {path}") from exc
        for line in raw_meta.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, sep, value = line.partition(":")
            if not sep:
                raise ValueError(f"Invalid frontmatter line in {path}: {line!r}")
            metadata[key.strip()] = value.strip().strip('"')
    if not metadata:
        raise ValueError(f"Prompt asset is missing frontmatter: {path}")
    return PromptAsset(path=path, metadata=metadata, body=body.strip())
