"""Filesystem helpers for vault artifact reads and writes."""
from __future__ import annotations

import os
from pathlib import Path


def ensure_inside(root: Path, target: Path) -> Path:
    root_resolved = root.resolve()
    target_resolved = target.resolve(strict=False)
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Path escapes root: {target}") from exc
    return target_resolved


def safe_mkdir(path: Path, *, root: Path) -> None:
    root_resolved = root.resolve(strict=False)
    if root.is_symlink():
        raise ValueError(f"Root cannot be a symlink: {root}")
    root.mkdir(parents=True, exist_ok=True)
    ensure_inside(root_resolved, path)
    current = root_resolved
    try:
        relative = path.absolute().relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Path is not lexically inside root: {path}") from exc
    for part in relative.parts:
        current = current / part
        if current.exists():
            if current.is_symlink():
                raise ValueError(f"Refusing to use symlinked directory: {current}")
            if not current.is_dir():
                raise ValueError(f"Expected directory but found file: {current}")
        else:
            current.mkdir()


def safe_write_text(path: Path, content: str, *, root: Path, encoding: str = "utf-8") -> None:
    safe_mkdir(path.parent, root=root)
    target = ensure_inside(root, path)
    if target.exists() and target.is_symlink():
        raise ValueError(f"Refusing to write through symlink: {target}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o644)
    with os.fdopen(fd, "w", encoding=encoding) as handle:
        handle.write(content)


def safe_append_text(path: Path, content: str, *, root: Path, encoding: str = "utf-8") -> None:
    safe_mkdir(path.parent, root=root)
    target = ensure_inside(root, path)
    if target.exists() and target.is_symlink():
        raise ValueError(f"Refusing to append through symlink: {target}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o644)
    with os.fdopen(fd, "a", encoding=encoding) as handle:
        handle.write(content)


def safe_write_bytes(path: Path, content: bytes, *, root: Path) -> None:
    safe_mkdir(path.parent, root=root)
    target = ensure_inside(root, path)
    if target.exists() and target.is_symlink():
        raise ValueError(f"Refusing to write through symlink: {target}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)


def safe_json_candidate(path: Path, *, root: Path) -> Path | None:
    if path.is_symlink():
        return None
    try:
        resolved = ensure_inside(root, path)
    except ValueError:
        return None
    if resolved.is_symlink() or not resolved.is_file():
        return None
    return resolved
