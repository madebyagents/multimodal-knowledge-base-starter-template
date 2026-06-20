"""Read-only Knowledge Hub HTTP client for the DanteDash cockpit."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx

READ_ONLY_ACTION_PATHS = {
    "/health",
    "/topology",
    "/kbs",
    "/retrieve",
    "/retrieve/agentic",
}

SENSITIVE_KEYS = {
    "absolute_path",
    "bridge_root",
    "canonical_workspace_root",
    "db_path",
    "dsn",
    "endpoint",
    "file_path",
    "index_dir",
    "knowledge_base_root",
    "path",
    "postgres_dsn",
    "private_bridge",
    "qdrant_url",
    "redis_url",
    "root",
    "roots",
    "runtime_root",
    "script_path",
    "secret",
    "shared_bridge",
    "source_path",
    "token",
}


def sanitize_public_payload(value: Any) -> Any:
    """Remove local paths, credentials, DSNs, and runtime roots from public JSON."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, inner in value.items():
            key_text = str(key)
            normalized = key_text.lower()
            if (
                normalized in SENSITIVE_KEYS
                or normalized.endswith("_root")
                or normalized.endswith("_endpoint")
                or (normalized.endswith("_path") and isinstance(inner, str) and _looks_like_local_path(inner))
                or normalized.endswith("_url")
                or normalized.endswith("_dsn")
                or "api_key" in normalized
                or "password" in normalized
                or "secret" in normalized
                or "token" in normalized
            ):
                continue
            sanitized[key_text] = sanitize_public_payload(inner)
        return sanitized
    if isinstance(value, list):
        return [sanitize_public_payload(item) for item in value]
    if isinstance(value, str) and _looks_like_local_path(value):
        return "[redacted-local-path]"
    return value


def _looks_like_local_path(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("~/") or "/Users/" in stripped:
        return True
    return stripped.startswith((
        "/Applications/",
        "/home/",
        "/opt/",
        "/private/",
        "/tmp/",
        "/Users/",
        "/var/",
        "/Volumes/",
    ))


class KnowledgeHubClient:
    """Small defensive client for the external Knowledge Hub runtime."""

    def __init__(
        self,
        *,
        base_url: str,
        actions_base_url: str,
        actions_bearer_token: str | None = None,
        timeout_s: float = 4.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.actions_base_url = actions_base_url.rstrip("/")
        self.actions_bearer_token = actions_bearer_token
        self.timeout_s = timeout_s
        self._http = http_client or httpx.Client(timeout=timeout_s, follow_redirects=False)

    def health(self) -> dict[str, Any]:
        return self._get_json("knowledge_hub", self.base_url, "/health")

    def topology(self) -> dict[str, Any]:
        return self._get_json("knowledge_hub", self.base_url, "/topology")

    def kbs(self, q: str = "") -> dict[str, Any]:
        params = {"q": q} if q else None
        return self._get_json("knowledge_hub", self.base_url, "/kbs", params=params)

    def retrieve(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("knowledge_hub", self.base_url, "/retrieve", payload)

    def dantedash_import_packages(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("knowledge_hub", self.base_url, "/dantedash/packages/import", payload, sanitize=True)

    def dantedash_search_packages(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("knowledge_hub", self.base_url, "/dantedash/packages/search", payload)

    def dantedash_search_packages_by_image(self, image_path: str | Path, *, top_k: int = 5) -> dict[str, Any]:
        path = Path(image_path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            with path.open("rb") as handle:
                return self._request_json(
                    "knowledge_hub",
                    "POST",
                    self.base_url,
                    "/dantedash/packages/search-image",
                    data={"top_k": str(max(1, min(int(top_k), 50)))},
                    files={"file": (path.name or "query.jpg", handle, content_type)},
                    timeout_s=max(self.timeout_s, 15.0),
                )
        except (OSError, ValueError):
            return _unavailable("knowledge_hub", "image_query_file_unavailable")

    def dantedash_package_stats(self) -> dict[str, Any]:
        return self._get_json("knowledge_hub", self.base_url, "/dantedash/packages/stats")

    def dantedash_package_items(self, *, limit: int | None = None, offset: int = 0) -> dict[str, Any]:
        params = {"offset": offset}
        if limit is not None:
            params["limit"] = limit
        return self._get_json("knowledge_hub", self.base_url, "/dantedash/packages/items", params=params)

    def dantedash_package_item(self, item_id: str, *, include_private: bool = False) -> dict[str, Any]:
        return self._get_json(
            "knowledge_hub",
            self.base_url,
            f"/dantedash/packages/items/{item_id}",
            params={"include_private": include_private},
            sanitize=not include_private,
        )

    def actions_health(self) -> dict[str, Any]:
        return self._get_json("actions_bridge", self.actions_base_url, "/health", actions=True)

    def actions_topology(self) -> dict[str, Any]:
        return self._get_json("actions_bridge", self.actions_base_url, "/topology", actions=True)

    def actions_openapi_operations(self) -> dict[str, Any]:
        raw = self._get_json(
            "actions_bridge",
            self.actions_base_url,
            "/openapi.json",
            actions=True,
            sanitize=False,
        )
        if not raw.get("ok"):
            return raw

        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        paths = data.get("paths") if isinstance(data, dict) else {}
        operations: list[dict[str, str]] = []
        if isinstance(paths, dict):
            for path, methods in sorted(paths.items()):
                if path not in READ_ONLY_ACTION_PATHS or not isinstance(methods, dict):
                    continue
                for method, operation in sorted(methods.items()):
                    method_lower = str(method).lower()
                    if method_lower not in {"get", "post"} or not isinstance(operation, dict):
                        continue
                    operations.append(
                        {
                            "method": method_lower.upper(),
                            "path": str(path),
                            "operation_id": str(operation.get("operationId") or ""),
                            "summary": str(operation.get("summary") or ""),
                        }
                    )
        return {
            **{k: raw[k] for k in ("ok", "surface", "status", "status_code") if k in raw},
            "data": {"operations": operations, "returned": len(operations)},
        }

    def close(self) -> None:
        self._http.close()

    def _get_json(
        self,
        surface: str,
        base_url: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        actions: bool = False,
        sanitize: bool = True,
    ) -> dict[str, Any]:
        return self._request_json(
            surface,
            "GET",
            base_url,
            path,
            params=params,
            actions=actions,
            sanitize=sanitize,
        )

    def _post_json(
        self,
        surface: str,
        base_url: str,
        path: str,
        payload: dict[str, Any],
        *,
        actions: bool = False,
        sanitize: bool = True,
    ) -> dict[str, Any]:
        return self._request_json(surface, "POST", base_url, path, json=payload, actions=actions, sanitize=sanitize)

    def _request_json(
        self,
        surface: str,
        method: str,
        base_url: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        actions: bool = False,
        sanitize: bool = True,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if actions and self.actions_bearer_token:
            headers["Authorization"] = f"Bearer {self.actions_bearer_token}"
        try:
            response = self._http.request(
                method,
                f"{base_url.rstrip('/')}/{path.lstrip('/')}",
                params=params,
                json=json,
                data=data,
                files=files,
                headers=headers,
                timeout=timeout_s,
            )
        except httpx.TimeoutException:
            return _unavailable(surface, "request_timeout")
        except httpx.RequestError:
            return _unavailable(surface, "service_unavailable")

        if response.status_code < 200 or response.status_code >= 300:
            return _unavailable(surface, "request_failed", status_code=response.status_code)
        try:
            data = response.json()
        except ValueError:
            return _unavailable(surface, "invalid_json", status_code=response.status_code)
        return {
            "ok": True,
            "surface": surface,
            "status": "available",
            "status_code": response.status_code,
            "data": sanitize_public_payload(data) if sanitize else data,
        }


def _unavailable(surface: str, error: str, *, status_code: int | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "surface": surface,
        "status": "unavailable",
        "status_code": status_code,
        "error": error,
    }
