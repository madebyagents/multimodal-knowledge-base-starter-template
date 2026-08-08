"""Read-only Git/license authority evidence for governed local sources.

The module deliberately treats the checked-in trust registry as the only
authority for the pinned HyperFrames subject.  GitHub observations and local
source bytes may prove that they match that subject, but neither a network
response nor a human-authored assertion can expand the registry's scope.
"""

from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import os
import re
import stat
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

TRUST_REGISTRY_SCHEMA_VERSION = "dantedash.governed_rights_trust_roots.v1"
ORIGIN_OBSERVATION_SCHEMA_VERSION = "dantedash.github_git_authority_observation.v1"
AUTHORITY_DECISION_SCHEMA_VERSION = "dantedash.governed_source_authority_decision.v1"
PRODUCER_ID = "dantedash.github-git-data-observer.v1"
POLICY_ENGINE_ID = "dantedash.apache-2.0-path-coverage.v1"
AUTHORITY_BASIS = "deterministic_registry_policy"
DEFAULT_TRUST_REGISTRY_PATH = (
    Path(__file__).parent / "dante_visual/manifests/governed_rights_trust_roots.v1.json"
)

OFFICIAL_REPOSITORY_ID = "heygen-com/hyperframes"
OFFICIAL_REPOSITORY_URL = "https://github.com/heygen-com/hyperframes"
OFFICIAL_API_ORIGIN = "https://api.github.com"
PINNED_SUBJECT_REVISION = "2935be6bf66d12f41ac768d841d567323b547357"
PINNED_SOURCE_TREE_PATH = "skills/hyperframes/palettes"
PINNED_SOURCE_PATHS = (
    "bold-energetic.md",
    "clean-corporate.md",
    "dark-premium.md",
    "jewel-rich.md",
    "monochrome.md",
    "nature-earth.md",
    "neon-electric.md",
    "pastel-soft.md",
    "warm-editorial.md",
)

SHA1_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SAFE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
SPDX_RE = re.compile(r"(?im)^\s*(?:<!--\s*)?SPDX-License-Identifier:\s*([^\s<]+)")
SOURCE_LICENSE_NOTICE_RE = re.compile(
    r"(?im)^\s*(?:<!--\s*)?(?:#{1,6}\s*)?(license|licence|notice)\s*:\s*(.+?)\s*(?:-->)?$"
)
CONTRARY_RIGHTS_RE = re.compile(
    r"(?im)^\s*(?:<!--\s*)?(?:copyright[^\n]*\ball rights reserved\b|"
    r"all rights reserved\b|proprietary(?:\s+license)?\s*:|"
    r"not for (?:redistribution|distribution)\b)"
)
LICENSE_MARKER_RE = re.compile(
    r"^(?:license|licence|copying|notice|copyright)(?:[._-].*)?$",
    re.IGNORECASE,
)

MAX_REGISTRY_BYTES = 256 * 1024
MAX_GITHUB_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_GITHUB_REQUESTS = 32
MAX_TREE_ENTRIES = 256
MAX_TOTAL_TREE_ENTRIES = 256
MAX_BLOB_BYTES = 1 * 1024 * 1024
GITHUB_REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_OBSERVATION_MAX_AGE = timedelta(hours=24)
NOFOLLOW_FLAG = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY_FLAG = getattr(os, "O_DIRECTORY", 0)
GITHUB_TRANSPORT_POLICY = {
    "policy_id": "github-https-verified-no-redirect.v1",
    "tls_verification": "required",
    "trust_environment": False,
    "redirects": "blocked",
    "timeout_seconds": GITHUB_REQUEST_TIMEOUT_SECONDS,
}
GIT_MODES_BY_TYPE = {
    "blob": {"100644", "100755", "120000"},
    "tree": {"040000"},
}
_PRODUCER_OWNED_CLIENTS: weakref.WeakSet[httpx.Client] = weakref.WeakSet()


@dataclass(frozen=True)
class FileSnapshot:
    """One immutable descriptor-backed file byte snapshot."""

    relative_path: str
    data: bytes
    size_bytes: int
    sha256: str
    git_blob_sha1: str


@dataclass(frozen=True)
class LoadedTrustRegistry:
    """Validated registry plus the hash/provenance callers must bind."""

    _raw_bytes: bytes = field(repr=False)
    sha256: str

    @property
    def payload(self) -> Mapping[str, Any]:
        """Return a fresh copy so callers cannot mutate the hash-bound registry."""

        payload = json.loads(self._raw_bytes)
        if not isinstance(payload, dict):  # guarded by ``load_trust_registry``
            raise ValueError("authority_registry_not_object")
        return payload

    @property
    def provenance(self) -> Mapping[str, Any]:
        return dict(self.payload["provenance"])


@dataclass(frozen=True)
class OriginObservationResult:
    """Public observation metadata and private in-memory blob snapshots."""

    observation: Mapping[str, Any] | None
    license_bytes: bytes | None
    source_bytes: Mapping[str, bytes]
    blockers: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.observation is not None and not self.blockers


@dataclass(frozen=True)
class AuthorityDecision:
    """Fail-closed source-level authority decision."""

    eligible: bool
    blockers: tuple[str, ...]
    evidence: Mapping[str, Any]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    """Return the Git object id for exactly ``data`` as a blob."""

    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - Git object identity


def git_tree_sha1(entries: Sequence[Mapping[str, Any]]) -> str:
    """Recompute a Git tree id from bounded, single-component entries."""

    validated_entries: list[Mapping[str, Any]] = []
    for entry in entries:
        name = entry.get("path")
        item_type = entry.get("type")
        declared_mode = entry.get("mode")
        object_id = entry.get("sha")
        if (
            _safe_relative_parts(name) is None
            or len(PurePosixPath(str(name)).parts) != 1
            or not isinstance(item_type, str)
            or not isinstance(declared_mode, str)
            or declared_mode not in GIT_MODES_BY_TYPE.get(item_type, set())
            or not SHA1_RE.fullmatch(str(object_id or ""))
        ):
            raise ValueError("authority_git_tree_entry_invalid")
        validated_entries.append(entry)

    body = bytearray()
    for entry in sorted(validated_entries, key=_git_tree_sort_key):
        name = str(entry["path"])
        item_type = str(entry.get("type") or "")
        declared_mode = str(entry["mode"])
        if declared_mode not in GIT_MODES_BY_TYPE.get(item_type, set()):
            raise ValueError("authority_git_tree_mode_invalid")
        mode = declared_mode.lstrip("0") or "0"
        body.extend(mode.encode("ascii"))
        body.extend(b" ")
        body.extend(name.encode("utf-8"))
        body.extend(b"\0")
        body.extend(bytes.fromhex(str(entry["sha"])))
    header = f"tree {len(body)}\0".encode("ascii")
    return hashlib.sha1(header + body).hexdigest()  # noqa: S324 - Git object identity


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def build_github_http_client() -> httpx.Client:
    """Build the only production client accepted by the origin producer."""

    client = httpx.Client(
        timeout=httpx.Timeout(GITHUB_REQUEST_TIMEOUT_SECONDS),
        follow_redirects=False,
        verify=True,
        trust_env=False,
        headers={"Accept": "application/vnd.github+json"},
    )
    _PRODUCER_OWNED_CLIENTS.add(client)
    return client


def snapshot_anchored_file(
    root: Path,
    relative_path: str,
    *,
    blocker_prefix: str = "authority_source",
    max_bytes: int = MAX_BLOB_BYTES,
) -> tuple[FileSnapshot | None, list[str]]:
    """Read a file through a no-follow descriptor chain rooted at ``root``.

    Every path component stays open while bytes are read.  The complete chain
    is then reopened and compared, so replacement of the root or any ancestor
    is detected instead of silently changing the source of truth.
    """

    parts = _safe_relative_parts(relative_path)
    if not parts:
        return None, [f"{blocker_prefix}_ref_invalid"]
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        return None, [f"{blocker_prefix}_max_bytes_invalid"]
    if not NOFOLLOW_FLAG or not DIRECTORY_FLAG:
        return None, [f"{blocker_prefix}_descriptor_guards_unsupported"]

    descriptors: list[int] = []
    identities: list[tuple[int, int, int, int, int]] = []
    try:
        descriptors, identities = _open_descriptor_chain(root, parts)
        file_stat = os.fstat(descriptors[-1])
        if not stat.S_ISREG(file_stat.st_mode):
            return None, [f"{blocker_prefix}_not_regular_file"]
        if file_stat.st_size > max_bytes:
            return None, [f"{blocker_prefix}_too_large"]

        data = _read_descriptor_bytes(descriptors[-1], max_bytes=max_bytes)
        after_stat = os.fstat(descriptors[-1])
        if (
            _stat_identity(after_stat) != identities[-1]
            or len(data) != after_stat.st_size
        ):
            return None, [f"{blocker_prefix}_changed_during_snapshot"]

        reopened: list[int] = []
        try:
            reopened, reopened_identities = _open_descriptor_chain(root, parts)
            if reopened_identities != identities:
                return None, [f"{blocker_prefix}_path_changed"]
        finally:
            _close_descriptors(reopened)

        return (
            FileSnapshot(
                relative_path=PurePosixPath(*parts).as_posix(),
                data=data,
                size_bytes=len(data),
                sha256=sha256_bytes(data),
                git_blob_sha1=git_blob_sha1(data),
            ),
            [],
        )
    except OSError as exc:
        return None, [_descriptor_blocker(blocker_prefix, exc)]
    finally:
        _close_descriptors(descriptors)


def load_trust_registry(path: Path) -> tuple[LoadedTrustRegistry | None, list[str]]:
    """Load the registry from one immutable descriptor snapshot."""

    snapshot, blockers = snapshot_anchored_file(
        path.parent,
        path.name,
        blocker_prefix="authority_registry",
        max_bytes=MAX_REGISTRY_BYTES,
    )
    if snapshot is None:
        return None, blockers
    try:
        payload = json.loads(snapshot.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, ["authority_registry_json_invalid"]
    if not isinstance(payload, dict):
        return None, ["authority_registry_not_object"]
    blockers = validate_trust_registry(payload)
    if blockers:
        return None, blockers
    return (
        LoadedTrustRegistry(
            _raw_bytes=snapshot.data,
            sha256=snapshot.sha256,
        ),
        [],
    )


def validate_trust_registry(registry: Mapping[str, Any]) -> list[str]:
    """Validate the exact, subject-bound HyperFrames trust-root schema."""

    blockers: list[str] = []
    if set(registry) != {
        "schema_version",
        "registry_id",
        "provenance",
        "repository",
        "subject",
        "license_policy",
        "policy_engine",
    }:
        return ["authority_registry_schema_invalid"]
    if registry.get("schema_version") != TRUST_REGISTRY_SCHEMA_VERSION:
        blockers.append("authority_registry_schema_version_mismatch")
    if not SAFE_ID_RE.fullmatch(str(registry.get("registry_id") or "")):
        blockers.append("authority_registry_id_invalid")

    expected_provenance = {
        "kind": "repository_reviewed_policy",
        "owner": "dantedash",
        "generated": False,
    }
    if registry.get("provenance") != expected_provenance:
        blockers.append("authority_registry_provenance_invalid")

    repository = registry.get("repository")
    expected_repository = {
        "repository_id": OFFICIAL_REPOSITORY_ID,
        "owner": "heygen-com",
        "name": "hyperframes",
        "https_url": OFFICIAL_REPOSITORY_URL,
        "api_origin": OFFICIAL_API_ORIGIN,
    }
    if repository != expected_repository:
        blockers.append("authority_registry_repository_untrusted")

    subject = registry.get("subject")
    if not isinstance(subject, Mapping) or set(subject) != {
        "commit_sha1",
        "root_tree_sha1",
        "tree_chain",
        "sources",
    }:
        blockers.append("authority_registry_subject_schema_invalid")
    else:
        if subject.get("commit_sha1") != PINNED_SUBJECT_REVISION:
            blockers.append("authority_registry_subject_revision_untrusted")
        if not SHA1_RE.fullmatch(str(subject.get("root_tree_sha1") or "")):
            blockers.append("authority_registry_root_tree_invalid")
        blockers.extend(_validate_registry_tree_chain(subject.get("tree_chain")))
        blockers.extend(_validate_registry_sources(subject.get("sources")))

    license_policy = registry.get("license_policy")
    if not isinstance(license_policy, Mapping) or set(license_policy) != {
        "policy_id",
        "spdx_id",
        "license_path",
        "license_blob_sha1",
        "license_sha256",
        "license_size_bytes",
        "notice_path",
        "notice_required",
        "path_marker_policy",
        "source_spdx_policy",
        "permitted_uses",
        "attribution_required",
        "trademark_rights_granted",
    }:
        blockers.append("authority_registry_license_policy_schema_invalid")
    else:
        expected_policy_values = {
            "policy_id": "apache-2.0-root-license-no-overrides",
            "spdx_id": "Apache-2.0",
            "license_path": "LICENSE",
            "notice_path": "NOTICE",
            "notice_required": False,
            "path_marker_policy": "root_license_only",
            "source_spdx_policy": "absent_or_apache-2.0",
            "permitted_uses": [
                "derived_summary",
                "external_provider_disclosure",
                "local_embedding",
            ],
            "attribution_required": True,
            "trademark_rights_granted": False,
        }
        for key, expected in expected_policy_values.items():
            if license_policy.get(key) != expected:
                blockers.append(f"authority_registry_license_policy_mismatch:{key}")
        if not SHA1_RE.fullmatch(str(license_policy.get("license_blob_sha1") or "")):
            blockers.append("authority_registry_license_blob_invalid")
        if not SHA256_RE.fullmatch(str(license_policy.get("license_sha256") or "")):
            blockers.append("authority_registry_license_sha256_invalid")
        if (
            not isinstance(license_policy.get("license_size_bytes"), int)
            or license_policy.get("license_size_bytes", 0) <= 0
        ):
            blockers.append("authority_registry_license_size_invalid")

    policy_engine = registry.get("policy_engine")
    expected_scope = {
        "repository_id": OFFICIAL_REPOSITORY_ID,
        "subject_revision": PINNED_SUBJECT_REVISION,
        "license_spdx_id": "Apache-2.0",
        "source_tree_path": PINNED_SOURCE_TREE_PATH,
        "source_paths": list(PINNED_SOURCE_PATHS),
    }
    if policy_engine != {
        "engine_id": POLICY_ENGINE_ID,
        "authority_mode": AUTHORITY_BASIS,
        "scope": expected_scope,
    }:
        blockers.append("authority_registry_policy_engine_scope_invalid")
    return _dedupe(blockers)


def observe_github_git_data(
    registry: LoadedTrustRegistry,
    *,
    http_client: httpx.Client,
    observed_at: datetime | None = None,
    allow_injected_test_transport: bool = False,
) -> OriginObservationResult:
    """Observe the pinned commit/tree/blob closure through GitHub Git Data.

    Requests are constructed from the fixed official API origin, never from
    response URLs.  Redirects, oversized responses, truncated trees, missing
    objects, unexpected entries, and byte/hash drift all fail closed.
    """

    registry_payload = registry.payload
    registry_blockers = validate_trust_registry(registry_payload)
    if registry_blockers:
        return OriginObservationResult(None, None, {}, tuple(registry_blockers))
    if not SHA256_RE.fullmatch(registry.sha256):
        return OriginObservationResult(
            None, None, {}, ("authority_registry_sha256_invalid",)
        )
    if http_client not in _PRODUCER_OWNED_CLIENTS and not allow_injected_test_transport:
        return OriginObservationResult(
            None, None, {}, ("authority_origin_transport_untrusted",)
        )

    reader = _GitHubReader(http_client)
    blockers: list[str] = []
    subject = registry_payload["subject"]
    repository = registry_payload["repository"]
    license_policy = registry_payload["license_policy"]
    slug = f"{repository['owner']}/{repository['name']}"
    commit_sha = str(subject["commit_sha1"])

    commit = reader.get_json(f"/repos/{slug}/git/commits/{commit_sha}", blockers)
    if commit is None:
        return OriginObservationResult(None, None, {}, tuple(_dedupe(blockers)))
    if commit.get("sha") != commit_sha:
        blockers.append("authority_origin_commit_mismatch")
    commit_tree = commit.get("tree")
    if (
        not isinstance(commit_tree, Mapping)
        or commit_tree.get("sha") != subject["root_tree_sha1"]
    ):
        blockers.append("authority_origin_root_tree_mismatch")

    closure_specs = [(".", str(subject["root_tree_sha1"]))]
    closure_specs.extend(
        (str(row["path"]), str(row["git_tree_sha1"])) for row in subject["tree_chain"]
    )
    closure: list[dict[str, Any]] = []
    tree_entries: dict[str, dict[str, Mapping[str, Any]]] = {}
    total_tree_entries = 0
    for tree_path, tree_sha in closure_specs:
        tree = reader.get_json(f"/repos/{slug}/git/trees/{tree_sha}", blockers)
        if tree is None:
            continue
        entries = _validated_tree_entries(tree, tree_path, tree_sha, blockers)
        if entries is None:
            continue
        tree_entries[tree_path] = entries
        normalized_entries = _normalized_tree_entries(entries.values())
        total_tree_entries += len(normalized_entries)
        if git_tree_sha1(normalized_entries) != tree_sha:
            blockers.append(f"authority_tree_object_id_mismatch:{tree_path}")
        closure.append(
            {
                "path": tree_path,
                "git_tree_sha1": tree_sha,
                "entry_count": len(entries),
                "entries_digest_sha256": canonical_json_sha256(normalized_entries),
                "entries": normalized_entries,
            }
        )
    if total_tree_entries > MAX_TOTAL_TREE_ENTRIES:
        blockers.append("authority_tree_closure_too_large")

    _validate_tree_chain_membership(subject, tree_entries, blockers)
    path_license_markers = _path_license_markers(tree_entries)
    if path_license_markers != [str(license_policy["license_path"])]:
        blockers.append("authority_path_license_override")

    root_entries = tree_entries.get(".", {})
    notice = root_entries.get(str(license_policy["notice_path"]))
    if notice is not None:
        blockers.append("authority_notice_present")
    license_entry = root_entries.get(str(license_policy["license_path"]))
    if not _entry_matches(
        license_entry,
        expected_type="blob",
        expected_mode="100644",
        expected_sha=str(license_policy["license_blob_sha1"]),
    ):
        blockers.append("authority_license_tree_binding_mismatch")

    license_bytes: bytes | None = None
    if license_entry is not None:
        license_bytes = reader.get_blob(
            slug,
            str(license_policy["license_blob_sha1"]),
            blockers,
            blocker_prefix="authority_license",
        )
        if license_bytes is not None:
            if len(license_bytes) != license_policy["license_size_bytes"]:
                blockers.append("authority_license_size_mismatch")
            if sha256_bytes(license_bytes) != license_policy["license_sha256"]:
                blockers.append("authority_license_sha256_mismatch")
            if git_blob_sha1(license_bytes) != license_policy["license_blob_sha1"]:
                blockers.append("authority_license_blob_mismatch")

    source_tree = tree_entries.get(PINNED_SOURCE_TREE_PATH, {})
    registry_sources = {
        str(row["relative_path"]): row
        for row in subject["sources"]
        if isinstance(row, Mapping)
    }
    source_snapshots: dict[str, bytes] = {}
    observed_sources: list[dict[str, Any]] = []
    if set(source_tree) != set(registry_sources):
        blockers.append("authority_source_tree_membership_mismatch")
    for relative_path, expected in sorted(registry_sources.items()):
        entry = source_tree.get(relative_path)
        if not _entry_matches(
            entry,
            expected_type="blob",
            expected_mode="100644",
            expected_sha=str(expected["git_blob_sha1"]),
        ):
            blockers.append(f"authority_source_tree_binding_mismatch:{relative_path}")
            continue
        data = reader.get_blob(
            slug,
            str(expected["git_blob_sha1"]),
            blockers,
            blocker_prefix=f"authority_source_blob:{relative_path}",
        )
        if data is None:
            continue
        source_snapshots[relative_path] = data
        source_sha256 = sha256_bytes(data)
        source_blob_sha1 = git_blob_sha1(data)
        if len(data) != expected["size_bytes"]:
            blockers.append(f"authority_source_size_mismatch:{relative_path}")
        if source_sha256 != expected["sha256"]:
            blockers.append(f"authority_source_sha256_mismatch:{relative_path}")
        if source_blob_sha1 != expected["git_blob_sha1"]:
            blockers.append(f"authority_source_blob_mismatch:{relative_path}")
        observed_sources.append(
            {
                "relative_path": relative_path,
                "size_bytes": len(data),
                "sha256": source_sha256,
                "git_blob_sha1": source_blob_sha1,
            }
        )

    blockers.extend(reader.blockers)
    blockers = _dedupe(blockers)
    if blockers:
        return OriginObservationResult(
            None, license_bytes, source_snapshots, tuple(blockers)
        )

    timestamp = observed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return OriginObservationResult(
            None,
            license_bytes,
            source_snapshots,
            ("authority_observed_at_timezone_invalid",),
        )
    observation = {
        "schema_version": ORIGIN_OBSERVATION_SCHEMA_VERSION,
        "producer_id": PRODUCER_ID,
        "registry_id": registry_payload["registry_id"],
        "registry_sha256": registry.sha256,
        "observed_at": timestamp.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "transport": dict(GITHUB_TRANSPORT_POLICY),
        "repository": dict(repository),
        "subject_revision": commit_sha,
        "root_tree_sha1": subject["root_tree_sha1"],
        "tree_closure": closure,
        "license": {
            "path": license_policy["license_path"],
            "spdx_id": license_policy["spdx_id"],
            "size_bytes": len(license_bytes or b""),
            "sha256": sha256_bytes(license_bytes or b""),
            "git_blob_sha1": git_blob_sha1(license_bytes or b""),
        },
        "notice": {"path": license_policy["notice_path"], "present": False},
        "path_license_markers": path_license_markers,
        "sources": observed_sources,
        "complete": True,
    }
    return OriginObservationResult(observation, license_bytes, source_snapshots, ())


def validate_origin_observation(
    registry: LoadedTrustRegistry,
    observation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_OBSERVATION_MAX_AGE,
) -> list[str]:
    """Validate one producer observation against the loaded trust root."""

    if not isinstance(observation, Mapping):
        return ["authority_observation_schema_invalid"]
    blockers: list[str] = []
    registry_payload = registry.payload
    expected_keys = {
        "schema_version",
        "producer_id",
        "registry_id",
        "registry_sha256",
        "observed_at",
        "transport",
        "repository",
        "subject_revision",
        "root_tree_sha1",
        "tree_closure",
        "license",
        "notice",
        "path_license_markers",
        "sources",
        "complete",
    }
    if set(observation) != expected_keys:
        return ["authority_observation_schema_invalid"]
    if observation.get("schema_version") != ORIGIN_OBSERVATION_SCHEMA_VERSION:
        blockers.append("authority_observation_schema_version_mismatch")
    if observation.get("producer_id") != PRODUCER_ID:
        blockers.append("authority_observation_producer_untrusted")
    if observation.get("registry_id") != registry_payload["registry_id"]:
        blockers.append("authority_observation_registry_id_mismatch")
    if observation.get("registry_sha256") != registry.sha256:
        blockers.append("authority_observation_registry_hash_mismatch")
    if observation.get("transport") != GITHUB_TRANSPORT_POLICY:
        blockers.append("authority_observation_transport_policy_mismatch")
    if observation.get("repository") != registry_payload["repository"]:
        blockers.append("authority_observation_origin_mismatch")
    subject = registry_payload["subject"]
    if observation.get("subject_revision") != subject["commit_sha1"]:
        blockers.append("authority_observation_subject_mismatch")
    if observation.get("root_tree_sha1") != subject["root_tree_sha1"]:
        blockers.append("authority_observation_root_tree_mismatch")
    if observation.get("complete") is not True:
        blockers.append("authority_observation_incomplete")

    expected_closure = [(".", subject["root_tree_sha1"])] + [
        (row["path"], row["git_tree_sha1"]) for row in subject["tree_chain"]
    ]
    closure = observation.get("tree_closure")
    closure_rows = closure if isinstance(closure, list) else []
    closure_entry_maps: dict[str, dict[str, Mapping[str, Any]]] = {}
    closure_invalid = (
        not isinstance(closure, list)
        or [
            (row.get("path"), row.get("git_tree_sha1"))
            for row in closure_rows
            if isinstance(row, Mapping)
        ]
        != expected_closure
    )
    total_tree_entries = 0
    for row in closure_rows:
        if not isinstance(row, Mapping) or set(row) != {
            "path",
            "git_tree_sha1",
            "entry_count",
            "entries_digest_sha256",
            "entries",
        }:
            closure_invalid = True
            continue
        entries = _observation_tree_entries(row.get("entries"))
        if entries is None:
            closure_invalid = True
            continue
        total_tree_entries += len(entries)
        closure_entry_maps[str(row.get("path"))] = {
            entry["path"]: entry for entry in entries
        }
        if (
            row.get("entry_count") != len(entries)
            or row.get("entries") != entries
            or row.get("entries_digest_sha256") != canonical_json_sha256(entries)
            or git_tree_sha1(entries) != row.get("git_tree_sha1")
        ):
            closure_invalid = True
    if total_tree_entries > MAX_TOTAL_TREE_ENTRIES:
        closure_invalid = True
    if closure_invalid:
        blockers.append("authority_observation_tree_closure_invalid")

    policy = registry_payload["license_policy"]
    expected_license = {
        "path": policy["license_path"],
        "spdx_id": policy["spdx_id"],
        "size_bytes": policy["license_size_bytes"],
        "sha256": policy["license_sha256"],
        "git_blob_sha1": policy["license_blob_sha1"],
    }
    if observation.get("license") != expected_license:
        blockers.append("authority_observation_license_mismatch")
    if observation.get("notice") != {"path": policy["notice_path"], "present": False}:
        blockers.append("authority_observation_notice_mismatch")
    observed_path_markers = _path_license_markers(closure_entry_maps)
    if observation.get(
        "path_license_markers"
    ) != observed_path_markers or observed_path_markers != [policy["license_path"]]:
        blockers.append("authority_observation_path_license_override")

    expected_sources = [
        {
            "relative_path": row["relative_path"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "git_blob_sha1": row["git_blob_sha1"],
        }
        for row in subject["sources"]
    ]
    if observation.get("sources") != expected_sources:
        blockers.append("authority_observation_source_bindings_mismatch")

    observed_at = _parse_utc_timestamp(observation.get("observed_at"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        blockers.append("authority_observation_now_timezone_invalid")
    elif observed_at is None:
        blockers.append("authority_observation_timestamp_invalid")
    elif observed_at > current + timedelta(minutes=5):
        blockers.append("authority_observation_from_future")
    elif current - observed_at > max_age:
        blockers.append("authority_observation_stale")
    return _dedupe(blockers)


def validate_source_authority(
    registry: LoadedTrustRegistry,
    observation: Mapping[str, Any],
    *,
    reviewer_id: str,
    source_relative_path: str,
    source_bytes: bytes,
    authority_basis: str = AUTHORITY_BASIS,
    requested_uses: Sequence[str] = ("local_embedding", "derived_summary"),
    now: datetime | None = None,
) -> AuthorityDecision:
    """Evaluate one source with the registry-authorized deterministic engine."""

    blockers = validate_origin_observation(registry, observation, now=now)
    registry_payload = registry.payload
    if authority_basis != AUTHORITY_BASIS:
        blockers.append("authority_manual_assertion_unsupported")
    if reviewer_id != POLICY_ENGINE_ID:
        blockers.append("authority_reviewer_unsupported")

    if not isinstance(source_bytes, bytes):
        blockers.append("authority_source_bytes_invalid")
        validated_source_bytes = b""
    else:
        validated_source_bytes = source_bytes

    source_rows = {
        str(row["relative_path"]): row
        for row in registry_payload["subject"]["sources"]
        if isinstance(row, Mapping)
    }
    expected = source_rows.get(source_relative_path)
    if expected is None:
        blockers.append("authority_source_out_of_scope")
        source_evidence = {
            "relative_path": "<out-of-scope>",
            "size_bytes": len(validated_source_bytes),
            "sha256": sha256_bytes(validated_source_bytes),
            "git_blob_sha1": git_blob_sha1(validated_source_bytes),
        }
    else:
        source_evidence = {
            "relative_path": source_relative_path,
            "size_bytes": len(validated_source_bytes),
            "sha256": sha256_bytes(validated_source_bytes),
            "git_blob_sha1": git_blob_sha1(validated_source_bytes),
        }
        if source_evidence["size_bytes"] != expected["size_bytes"]:
            blockers.append("authority_source_size_mismatch")
        if source_evidence["sha256"] != expected["sha256"]:
            blockers.append("authority_source_sha256_mismatch")
        if source_evidence["git_blob_sha1"] != expected["git_blob_sha1"]:
            blockers.append("authority_source_blob_mismatch")

    policy = registry_payload["license_policy"]
    if not isinstance(requested_uses, Sequence) or isinstance(
        requested_uses, (str, bytes)
    ):
        blockers.append("authority_requested_uses_invalid")
        normalized_uses: list[str] = []
    else:
        normalized_uses = sorted(set(str(item) for item in requested_uses))
        if not normalized_uses or not set(normalized_uses) <= set(
            policy["permitted_uses"]
        ):
            blockers.append("authority_requested_use_not_permitted")

    blockers.extend(_source_license_metadata_blockers(validated_source_bytes, policy))

    blockers = _dedupe(blockers)
    try:
        observation_sha256 = canonical_json_sha256(observation)
    except (TypeError, ValueError):
        blockers = _dedupe(
            [*blockers, "authority_observation_canonicalization_invalid"]
        )
        observation_sha256 = ""

    evidence = {
        "schema_version": AUTHORITY_DECISION_SCHEMA_VERSION,
        "decision": "eligible" if not blockers else "blocked",
        "authority_basis": authority_basis,
        "reviewer_id": reviewer_id,
        "trust_registry": {
            "registry_id": registry_payload["registry_id"],
            "sha256": registry.sha256,
            "provenance": dict(registry.provenance),
        },
        "origin_observation_sha256": observation_sha256,
        "repository": {
            "repository_id": OFFICIAL_REPOSITORY_ID,
            "https_url": OFFICIAL_REPOSITORY_URL,
            "subject_revision": PINNED_SUBJECT_REVISION,
        },
        "license_policy": {
            "policy_id": policy["policy_id"],
            "spdx_id": policy["spdx_id"],
            "license_sha256": policy["license_sha256"],
            "attribution_required": policy["attribution_required"],
            "trademark_rights_granted": policy["trademark_rights_granted"],
        },
        "source": source_evidence,
        "requested_uses": normalized_uses,
        "blockers": blockers,
    }
    return AuthorityDecision(not blockers, tuple(blockers), evidence)


class _GitHubReader:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self._request_count = 0
        self.blockers: list[str] = []

    def get_json(self, path: str, blockers: list[str]) -> Mapping[str, Any] | None:
        if self._request_count >= MAX_GITHUB_REQUESTS:
            blockers.append("authority_origin_request_limit_exceeded")
            return None
        self._request_count += 1
        url = f"{OFFICIAL_API_ORIGIN}{path}"
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            blockers.append("authority_origin_url_untrusted")
            return None
        try:
            with self._client.stream(
                "GET",
                url,
                follow_redirects=False,
                headers={"Accept": "application/vnd.github+json"},
                timeout=GITHUB_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                if response.request.url != httpx.URL(url):
                    blockers.append("authority_origin_request_url_mismatch")
                    return None
                if response.is_redirect:
                    blockers.append("authority_origin_redirect_not_allowed")
                    return None
                if response.status_code != 200:
                    blockers.append(
                        f"authority_origin_http_status:{response.status_code}"
                    )
                    return None
                length = response.headers.get("content-length")
                if (
                    length
                    and length.isdigit()
                    and int(length) > MAX_GITHUB_RESPONSE_BYTES
                ):
                    blockers.append("authority_origin_response_too_large")
                    return None
                chunks: list[bytes] = []
                observed = 0
                for chunk in response.iter_bytes():
                    observed += len(chunk)
                    if observed > MAX_GITHUB_RESPONSE_BYTES:
                        blockers.append("authority_origin_response_too_large")
                        return None
                    chunks.append(chunk)
        except (httpx.TimeoutException, httpx.RequestError):
            blockers.append("authority_origin_request_failed")
            return None
        try:
            payload = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError):
            blockers.append("authority_origin_json_invalid")
            return None
        if not isinstance(payload, Mapping):
            blockers.append("authority_origin_payload_invalid")
            return None
        return payload

    def get_blob(
        self,
        slug: str,
        blob_sha: str,
        blockers: list[str],
        *,
        blocker_prefix: str,
    ) -> bytes | None:
        payload = self.get_json(f"/repos/{slug}/git/blobs/{blob_sha}", blockers)
        if payload is None:
            return None
        if payload.get("sha") != blob_sha or payload.get("encoding") != "base64":
            blockers.append(f"{blocker_prefix}_response_invalid")
            return None
        size = payload.get("size")
        content = payload.get("content")
        if (
            not isinstance(size, int)
            or size < 0
            or size > MAX_BLOB_BYTES
            or not isinstance(content, str)
        ):
            blockers.append(f"{blocker_prefix}_response_invalid")
            return None
        try:
            data = base64.b64decode("".join(content.splitlines()), validate=True)
        except (ValueError, binascii.Error):
            blockers.append(f"{blocker_prefix}_base64_invalid")
            return None
        if len(data) != size or git_blob_sha1(data) != blob_sha:
            blockers.append(f"{blocker_prefix}_identity_mismatch")
            return None
        return data


def _safe_relative_parts(relative_path: Any) -> tuple[str, ...] | None:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        return None
    try:
        relative_path.encode("utf-8")
    except UnicodeEncodeError:
        return None
    path = PurePosixPath(relative_path)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return tuple(path.parts)


def _open_descriptor_chain(
    root: Path,
    parts: Sequence[str],
) -> tuple[list[int], list[tuple[int, int, int, int, int]]]:
    descriptors: list[int] = []
    identities: list[tuple[int, int, int, int, int]] = []
    directory_flags = os.O_RDONLY | DIRECTORY_FLAG | NOFOLLOW_FLAG
    file_flags = os.O_RDONLY | NOFOLLOW_FLAG
    try:
        root_fd = os.open(root, directory_flags)
        descriptors.append(root_fd)
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise OSError(errno.ENOTDIR, "root is not a directory")
        identities.append(_stat_identity(root_stat))
        parent_fd = root_fd
        for index, part in enumerate(parts):
            is_last = index == len(parts) - 1
            item_lstat = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(item_lstat.st_mode):
                raise OSError(errno.ELOOP, "symlink is not allowed")
            descriptor = os.open(
                part,
                file_flags if is_last else directory_flags,
                dir_fd=parent_fd,
            )
            descriptors.append(descriptor)
            item_stat = os.fstat(descriptor)
            if not is_last and not stat.S_ISDIR(item_stat.st_mode):
                raise OSError(errno.ENOTDIR, "ancestor is not a directory")
            identities.append(_stat_identity(item_stat))
            parent_fd = descriptor
        return descriptors, identities
    except Exception:
        _close_descriptors(descriptors)
        raise


def _read_descriptor_bytes(descriptor: int, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = os.read(descriptor, min(64 * 1024, max_bytes + 1 - observed))
        if not chunk:
            return b"".join(chunks)
        observed += len(chunk)
        if observed > max_bytes:
            raise OSError(errno.EFBIG, "file exceeds byte bound")
        chunks.append(chunk)


def _close_descriptors(descriptors: Sequence[int]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)


def _descriptor_blocker(prefix: str, exc: OSError) -> str:
    if exc.errno in {errno.ELOOP, errno.EMLINK}:
        return f"{prefix}_symlink_not_allowed"
    if exc.errno == errno.ENOENT:
        return f"{prefix}_missing"
    if exc.errno in {errno.ENOTDIR, errno.EISDIR}:
        return f"{prefix}_path_component_invalid"
    if exc.errno == errno.EFBIG:
        return f"{prefix}_too_large"
    return f"{prefix}_unreadable"


def _validate_registry_tree_chain(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != 3:
        return ["authority_registry_tree_chain_invalid"]
    expected_paths = ["skills", "skills/hyperframes", PINNED_SOURCE_TREE_PATH]
    blockers: list[str] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping) or set(row) != {"path", "git_tree_sha1"}:
            blockers.append(f"authority_registry_tree_chain_row_invalid:{index}")
            continue
        if row.get("path") != expected_paths[index]:
            blockers.append(f"authority_registry_tree_chain_path_mismatch:{index}")
        if not SHA1_RE.fullmatch(str(row.get("git_tree_sha1") or "")):
            blockers.append(f"authority_registry_tree_chain_sha_invalid:{index}")
    return blockers


def _validate_registry_sources(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != len(PINNED_SOURCE_PATHS):
        return ["authority_registry_source_set_invalid"]
    blockers: list[str] = []
    observed_paths: list[str] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping) or set(row) != {
            "relative_path",
            "size_bytes",
            "git_blob_sha1",
            "sha256",
        }:
            blockers.append(f"authority_registry_source_row_invalid:{index}")
            continue
        path = row.get("relative_path")
        if _safe_relative_parts(path) is None or PurePosixPath(
            str(path)
        ).parent != PurePosixPath("."):
            blockers.append(f"authority_registry_source_path_invalid:{index}")
        else:
            observed_paths.append(str(path))
        if not isinstance(row.get("size_bytes"), int) or row.get("size_bytes", 0) <= 0:
            blockers.append(f"authority_registry_source_size_invalid:{index}")
        if not SHA1_RE.fullmatch(str(row.get("git_blob_sha1") or "")):
            blockers.append(f"authority_registry_source_blob_invalid:{index}")
        if not SHA256_RE.fullmatch(str(row.get("sha256") or "")):
            blockers.append(f"authority_registry_source_sha256_invalid:{index}")
    if observed_paths != list(PINNED_SOURCE_PATHS):
        blockers.append("authority_registry_source_set_invalid")
    return blockers


def _validated_tree_entries(
    tree: Mapping[str, Any],
    tree_path: str,
    expected_sha: str,
    blockers: list[str],
) -> dict[str, Mapping[str, Any]] | None:
    if tree.get("sha") != expected_sha:
        blockers.append(f"authority_tree_sha_mismatch:{tree_path}")
    if tree.get("truncated") is not False:
        blockers.append(f"authority_tree_incomplete:{tree_path}")
        return None
    rows = tree.get("tree")
    if not isinstance(rows, list) or len(rows) > MAX_TREE_ENTRIES:
        blockers.append(f"authority_tree_entries_invalid:{tree_path}")
        return None
    entries: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            blockers.append(f"authority_tree_entry_invalid:{tree_path}")
            continue
        name = row.get("path")
        item_type = row.get("type")
        mode = row.get("mode")
        if (
            not isinstance(name, str)
            or _safe_relative_parts(name) is None
            or len(PurePosixPath(name).parts) != 1
            or not isinstance(item_type, str)
            or item_type not in {"blob", "tree"}
            or not isinstance(mode, str)
            or mode not in GIT_MODES_BY_TYPE.get(item_type, set())
            or not SHA1_RE.fullmatch(str(row.get("sha") or ""))
        ):
            blockers.append(f"authority_tree_entry_invalid:{tree_path}")
            continue
        if name in entries:
            blockers.append(f"authority_tree_duplicate_entry:{tree_path}:{name}")
            continue
        entries[name] = row
    return entries


def _normalized_tree_entries(
    entries: Sequence[Mapping[str, Any]] | Any,
) -> list[dict[str, str]]:
    return sorted(
        [
            {
                "path": str(row["path"]),
                "mode": str(row["mode"]),
                "type": str(row["type"]),
                "sha": str(row["sha"]),
            }
            for row in entries
        ],
        key=_git_tree_sort_key,
    )


def _observation_tree_entries(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list) or len(value) > MAX_TREE_ENTRIES:
        return None
    for row in value:
        item_type = row.get("type") if isinstance(row, Mapping) else None
        mode = row.get("mode") if isinstance(row, Mapping) else None
        if (
            not isinstance(row, Mapping)
            or set(row) != {"path", "mode", "type", "sha"}
            or _safe_relative_parts(row.get("path")) is None
            or len(PurePosixPath(str(row.get("path"))).parts) != 1
            or not isinstance(item_type, str)
            or item_type not in {"blob", "tree"}
            or not isinstance(mode, str)
            or mode not in GIT_MODES_BY_TYPE.get(item_type, set())
            or not SHA1_RE.fullmatch(str(row.get("sha") or ""))
        ):
            return None
    normalized = _normalized_tree_entries(value)
    if len({row["path"] for row in normalized}) != len(normalized):
        return None
    return normalized


def _git_tree_sort_key(entry: Mapping[str, Any]) -> bytes:
    suffix = "/" if entry.get("type") == "tree" else ""
    return f"{entry['path']}{suffix}".encode("utf-8")


def _validate_tree_chain_membership(
    subject: Mapping[str, Any],
    trees: Mapping[str, Mapping[str, Mapping[str, Any]]],
    blockers: list[str],
) -> None:
    parent_path = "."
    for row in subject["tree_chain"]:
        child_path = str(row["path"])
        entry = trees.get(parent_path, {}).get(PurePosixPath(child_path).name)
        if not _entry_matches(
            entry,
            expected_type="tree",
            expected_mode="040000",
            expected_sha=str(row["git_tree_sha1"]),
        ):
            blockers.append(f"authority_tree_chain_mismatch:{child_path}")
        parent_path = child_path


def _entry_matches(
    entry: Mapping[str, Any] | None,
    *,
    expected_type: str,
    expected_mode: str,
    expected_sha: str,
) -> bool:
    return bool(
        entry
        and entry.get("type") == expected_type
        and entry.get("mode") == expected_mode
        and entry.get("sha") == expected_sha
    )


def _path_license_markers(
    trees: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[str]:
    markers: list[str] = []
    for tree_path, entries in trees.items():
        for name in entries:
            if LICENSE_MARKER_RE.fullmatch(name):
                markers.append(name if tree_path == "." else f"{tree_path}/{name}")
    return sorted(markers)


def _source_license_metadata_blockers(
    source_bytes: bytes,
    policy: Mapping[str, Any],
) -> list[str]:
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ["authority_source_text_encoding_invalid"]

    blockers: list[str] = []
    spdx_identifiers = sorted(set(SPDX_RE.findall(source_text)))
    if any(identifier != policy["spdx_id"] for identifier in spdx_identifiers):
        blockers.append("authority_source_contrary_spdx")
    if CONTRARY_RIGHTS_RE.search(source_text):
        blockers.append("authority_source_contrary_rights_reservation")
    for marker, value in SOURCE_LICENSE_NOTICE_RE.findall(source_text):
        if marker.lower() == "notice":
            blockers.append("authority_source_unresolved_notice")
        elif (
            "apache-2.0" not in value.lower()
            and "apache license 2.0" not in value.lower()
        ):
            blockers.append("authority_source_contrary_license_metadata")
    return _dedupe(blockers)


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))
