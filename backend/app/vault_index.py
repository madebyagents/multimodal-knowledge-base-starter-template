"""External Dante vault text index over the prebuilt Voyage 2048 SQLite store."""
from __future__ import annotations

import array
import json
import logging
import math
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("kb.vault_index")


DEFAULT_INDEX_DIR = Path("/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/smart-external-voyage-2048")
DEFAULT_SCRIPT_PATH = Path("/Users/vidigal/claude-code/Obsidian/scripts/external_vault_vector_index.py")
DEFAULT_EMBEDDING_ENDPOINT = "http://127.0.0.1:9632/v1/embeddings"
DEFAULT_MODEL = "voyage-4-large"
DEFAULT_RERANK_MODEL = "rerank-v4.0-pro"
DEFAULT_RERANK_ENDPOINT = "https://api.cohere.com/v2/rerank"


@dataclass
class VaultIndexResult:
    rank: int
    rel_path: str
    chunk_index: int
    score: float
    vector_score: float
    rerank_score: float | None
    snippet: str


class VaultVectorIndex:
    """Query and maintain the external Dante vault text-vector index."""

    def __init__(
        self,
        *,
        index_dir: Path = DEFAULT_INDEX_DIR,
        script_path: Path = DEFAULT_SCRIPT_PATH,
        embedding_endpoint: str = DEFAULT_EMBEDDING_ENDPOINT,
        embedding_model: str = DEFAULT_MODEL,
        cohere_api_key: str | None = None,
        rerank_model: str = DEFAULT_RERANK_MODEL,
        rerank_endpoint: str = DEFAULT_RERANK_ENDPOINT,
    ) -> None:
        self.index_dir = Path(index_dir)
        self.db_path = self.index_dir / "index.sqlite"
        self.report_path = self.index_dir / "reports" / "latest-build-report.json"
        self.script_path = Path(script_path)
        self.embedding_endpoint = embedding_endpoint
        self.embedding_model = embedding_model
        self.cohere_api_key = cohere_api_key
        self.rerank_model = rerank_model
        self.rerank_endpoint = rerank_endpoint

    def inspect(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {
                "ok": False,
                "index_dir": str(self.index_dir),
                "db_path": str(self.db_path),
                "reason": "index_not_found",
            }
        with self._connect() as conn:
            counts = {
                "ok": True,
                "index_dir": str(self.index_dir),
                "db_path": str(self.db_path),
                "report_path": str(self.report_path),
                "files_indexed": conn.execute("SELECT COUNT(*) FROM files WHERE status = 'indexed'").fetchone()[0],
                "files_skipped": conn.execute("SELECT COUNT(*) FROM files WHERE status != 'indexed'").fetchone()[0],
                "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "embeddings": conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0],
                "dimensions": [
                    {"dimensions": row[0], "count": row[1]}
                    for row in conn.execute("SELECT dimensions, COUNT(*) FROM embeddings GROUP BY dimensions")
                ],
                "models": [
                    {"model": row[0], "count": row[1]}
                    for row in conn.execute("SELECT model, COUNT(*) FROM embeddings GROUP BY model")
                ],
            }
        if self.report_path.exists():
            try:
                report = json.loads(self.report_path.read_text(encoding="utf-8"))
                counts["latest_build"] = {
                    "selected_files": report.get("selected_files"),
                    "selected_mb": report.get("selected_mb"),
                    "stats": report.get("stats"),
                    "db_counts": report.get("db_counts"),
                    "finished_at": report.get("finished_at"),
                    "skipped": report.get("skipped"),
                }
            except (OSError, json.JSONDecodeError):
                counts["latest_build"] = None
        return counts

    def health(self, *, check_embedding: bool = False) -> dict[str, Any]:
        status = self.inspect()
        status.update(
            {
                "embedding_endpoint": self.embedding_endpoint,
                "embedding_model": self.embedding_model,
                "rerank_model": self.rerank_model,
                "rerank_enabled": bool(self.cohere_api_key),
                "script_path": str(self.script_path),
                "script_exists": self.script_path.exists(),
            }
        )
        if check_embedding:
            try:
                vector = self.embed_query("health ping")
                status["embedding_check"] = {"ok": True, "dimensions": len(vector)}
            except Exception as exc:  # noqa: BLE001
                status["embedding_check"] = {
                    "ok": False,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
        return status

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        candidate_k: int = 80,
        use_rerank: bool = True,
        snippet_chars: int = 900,
    ) -> list[VaultIndexResult]:
        if not self.db_path.exists():
            raise FileNotFoundError(self.db_path)
        query_vector = self.embed_query(query)
        query_array = array.array("f", _normalize(query_vector))

        with self._connect() as conn:
            scored: list[tuple[float, str]] = []
            for row in conn.execute(
                "SELECT chunk_id, vector FROM embeddings WHERE model = ?",
                (self.embedding_model,),
            ):
                score = _dot(query_array, _blob_to_array(row["vector"]))
                scored.append((score, row["chunk_id"]))
            scored.sort(reverse=True)
            candidate_ids = [chunk_id for _, chunk_id in scored[:candidate_k]]
            score_by_id = {chunk_id: score for score, chunk_id in scored[:candidate_k]}
            if not candidate_ids:
                return []

            placeholders = ",".join("?" for _ in candidate_ids)
            rows_by_id = {
                row["chunk_id"]: dict(row)
                for row in conn.execute(
                    f"""
                    SELECT chunk_id, rel_path, chunk_index, start_char, end_char, text, text_sha256
                    FROM chunks
                    WHERE chunk_id IN ({placeholders})
                    """,
                    candidate_ids,
                )
            }

        candidates: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        for chunk_id in candidate_ids:
            row = rows_by_id.get(chunk_id)
            if not row:
                continue
            text_hash = row.get("text_sha256")
            if text_hash and text_hash in seen_hashes:
                continue
            if text_hash:
                seen_hashes.add(text_hash)
            row["vector_score"] = float(score_by_id[chunk_id])
            candidates.append(row)

        ranked = self._rerank(query, candidates, top_k=top_k) if use_rerank and self.cohere_api_key else None
        if ranked is None:
            ranked = candidates[:top_k]

        results: list[VaultIndexResult] = []
        for idx, row in enumerate(ranked[:top_k], start=1):
            vector_score = float(row.get("vector_score") or 0.0)
            rerank_score = row.get("rerank_score")
            score = float(rerank_score) if rerank_score is not None else vector_score
            results.append(
                VaultIndexResult(
                    rank=idx,
                    rel_path=str(row["rel_path"]),
                    chunk_index=int(row["chunk_index"]),
                    score=score,
                    vector_score=vector_score,
                    rerank_score=float(rerank_score) if rerank_score is not None else None,
                    snippet=_one_line(str(row["text"]))[:snippet_chars],
                )
            )
        return results

    def reindex(
        self,
        *,
        dry_run: bool = False,
        include_generated: bool = False,
        include_sensitive: bool = False,
        max_file_bytes: int = 2_500_000,
        timeout_s: int = 3600,
    ) -> dict[str, Any]:
        if not self.script_path.exists():
            raise FileNotFoundError(self.script_path)
        args = [str(self.script_path), "build"]
        if dry_run:
            args.append("--dry-run")
        if include_generated:
            args.append("--include-generated")
        if include_sensitive:
            args.append("--include-sensitive")
        args.extend(["--max-file-bytes", str(max_file_bytes)])
        proc = subprocess.run(
            args,
            cwd=str(self.script_path.parent.parent),
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        parsed = _parse_last_json(proc.stdout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "dry_run": dry_run,
            "stdout_tail": proc.stdout[-8000:],
            "stderr_tail": proc.stderr[-4000:],
            "report": parsed,
        }

    def embed_query(self, text: str) -> list[float]:
        response = httpx.post(
            self.embedding_endpoint,
            json={"model": self.embedding_model, "input": [text]},
            timeout=90.0,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Voyage proxy HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        try:
            vector = body["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Voyage proxy response did not include data[0].embedding") from exc
        return [float(v) for v in vector]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _rerank(self, query: str, rows: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]] | None:
        if not rows or not self.cohere_api_key:
            return None
        response = httpx.post(
            self.rerank_endpoint,
            headers={
                "Authorization": f"Bearer {self.cohere_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.rerank_model,
                "query": query,
                "documents": [str(row.get("text") or "")[:4096] for row in rows],
                "top_n": min(top_k, len(rows)),
            },
            timeout=90.0,
        )
        if response.status_code >= 400:
            logger.warning("Cohere rerank failed: HTTP %s %s", response.status_code, response.text[:300])
            return None
        ranked: list[dict[str, Any]] = []
        for item in response.json().get("results", []):
            idx = item.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(rows):
                continue
            row = dict(rows[idx])
            if item.get("relevance_score") is not None:
                row["rerank_score"] = float(item["relevance_score"])
            ranked.append(row)
        return ranked or None


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0:
        return vector
    return [v / norm for v in vector]


def _blob_to_array(blob: bytes) -> array.array:
    values = array.array("f")
    values.frombytes(blob)
    return values


def _dot(a: array.array, b: array.array) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _parse_last_json(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        return None
    for idx in range(len(text) - 1, -1, -1):
        if text[idx] != "{":
            continue
        try:
            return json.loads(text[idx:])
        except json.JSONDecodeError:
            continue
    return None


def build_from_env() -> VaultVectorIndex:
    """Create the index client from environment variables."""
    return VaultVectorIndex(
        index_dir=Path(os.getenv("DANTE_VAULT_INDEX_DIR", str(DEFAULT_INDEX_DIR))),
        script_path=Path(os.getenv("DANTE_VAULT_INDEX_SCRIPT", str(DEFAULT_SCRIPT_PATH))),
        embedding_endpoint=os.getenv("DANTE_VAULT_INDEX_EMBEDDING_ENDPOINT", DEFAULT_EMBEDDING_ENDPOINT),
        embedding_model=os.getenv("DANTE_VAULT_INDEX_EMBEDDING_MODEL", DEFAULT_MODEL),
        cohere_api_key=os.getenv("COHERE_API_KEY", "").strip() or None,
        rerank_model=os.getenv("COHERE_RERANK_MODEL", DEFAULT_RERANK_MODEL),
        rerank_endpoint=os.getenv("COHERE_RERANK_ENDPOINT", DEFAULT_RERANK_ENDPOINT),
    )
