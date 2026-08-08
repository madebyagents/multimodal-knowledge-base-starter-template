from __future__ import annotations

import base64
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import governed_authority_evidence as subject


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "app/dante_visual/manifests/governed_rights_trust_roots.v1.json"
)
FIXED_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def test_checked_in_registry_is_exact_and_subject_bound() -> None:
    registry, blockers = subject.load_trust_registry(REGISTRY_PATH)

    assert blockers == []
    assert registry is not None
    assert registry.payload["repository"]["repository_id"] == "heygen-com/hyperframes"
    assert registry.payload["subject"]["commit_sha1"] == subject.PINNED_SUBJECT_REVISION
    assert [
        row["relative_path"] for row in registry.payload["subject"]["sources"]
    ] == list(subject.PINNED_SOURCE_PATHS)
    assert registry.payload["policy_engine"]["engine_id"] == subject.POLICY_ENGINE_ID
    assert len(registry.sha256) == 64


def test_git_blob_sha1_matches_git_object_identity() -> None:
    assert (
        subject.git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    )


def test_unhashable_tree_type_and_mode_fail_closed() -> None:
    blockers: list[str] = []
    tree = {
        "sha": "a" * 40,
        "truncated": False,
        "tree": [
            {
                "path": "palette.md",
                "mode": [],
                "type": [],
                "sha": "b" * 40,
            }
        ],
    }

    entries = subject._validated_tree_entries(tree, ".", "a" * 40, blockers)

    assert entries == {}
    assert blockers == ["authority_tree_entry_invalid:."]
    assert subject._observation_tree_entries(tree["tree"]) is None


def test_surrogate_tree_path_is_rejected_before_utf8_encoding() -> None:
    entry = {
        "path": "\ud800",
        "mode": "100644",
        "type": "blob",
        "sha": "b" * 40,
    }

    with pytest.raises(ValueError, match="authority_git_tree_entry_invalid"):
        subject.git_tree_sha1([entry])
    assert subject._observation_tree_entries([entry]) is None


def test_descriptor_snapshot_rejects_symlink_component(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    real_dir = tmp_path / "real"
    source_root.mkdir()
    real_dir.mkdir()
    (real_dir / "palette.md").write_bytes(b"palette")
    (source_root / "nested").symlink_to(real_dir, target_is_directory=True)

    snapshot, blockers = subject.snapshot_anchored_file(
        source_root, "nested/palette.md"
    )

    assert snapshot is None
    assert blockers == ["authority_source_symlink_not_allowed"]


def test_descriptor_snapshot_detects_ancestor_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "source"
    nested = source_root / "nested"
    nested.mkdir(parents=True)
    (nested / "palette.md").write_bytes(b"immutable palette")
    moved_root = tmp_path / "moved-source"
    original_reader = subject._read_descriptor_bytes

    def replace_ancestor(descriptor: int, *, max_bytes: int) -> bytes:
        source_root.rename(moved_root)
        replacement = source_root / "nested"
        replacement.mkdir(parents=True)
        (replacement / "palette.md").write_bytes(b"immutable palette")
        return original_reader(descriptor, max_bytes=max_bytes)

    monkeypatch.setattr(subject, "_read_descriptor_bytes", replace_ancestor)

    snapshot, blockers = subject.snapshot_anchored_file(
        source_root, "nested/palette.md"
    )

    assert snapshot is None
    assert blockers == ["authority_source_path_changed"]


def test_offline_git_observation_and_policy_engine_decision_are_green(
    tmp_path: Path,
) -> None:
    registry, result, source_bytes = make_observation_fixture(tmp_path)

    assert result.ok is True
    assert result.observation is not None
    source_path = "clean-corporate.md"
    decision = subject.validate_source_authority(
        registry,
        result.observation,
        reviewer_id=subject.POLICY_ENGINE_ID,
        source_relative_path=source_path,
        source_bytes=source_bytes[source_path],
        requested_uses=(
            "local_embedding",
            "derived_summary",
            "external_provider_disclosure",
        ),
        now=FIXED_NOW,
    )

    assert decision.eligible is True
    assert decision.blockers == ()
    assert decision.evidence["trust_registry"] == {
        "registry_id": registry.payload["registry_id"],
        "sha256": registry.sha256,
        "provenance": registry.payload["provenance"],
    }
    assert source_bytes[source_path].decode("utf-8") not in json.dumps(
        decision.evidence
    )


def test_forged_origin_is_rejected(tmp_path: Path) -> None:
    registry, result, source_bytes = make_observation_fixture(tmp_path)
    assert result.observation is not None
    forged = copy.deepcopy(result.observation)
    forged["repository"]["https_url"] = "https://example.invalid/forged"

    decision = subject.validate_source_authority(
        registry,
        forged,
        reviewer_id=subject.POLICY_ENGINE_ID,
        source_relative_path="clean-corporate.md",
        source_bytes=source_bytes["clean-corporate.md"],
        now=FIXED_NOW,
    )

    assert decision.eligible is False
    assert "authority_observation_origin_mismatch" in decision.blockers


def test_malformed_non_object_observation_fails_closed(tmp_path: Path) -> None:
    registry, _result, _source_bytes = make_observation_fixture(tmp_path)

    blockers = subject.validate_origin_observation(
        registry,
        None,  # type: ignore[arg-type]
        now=FIXED_NOW,
    )

    assert blockers == ["authority_observation_schema_invalid"]


def test_tree_closure_digest_is_recomputed(tmp_path: Path) -> None:
    registry, result, source_bytes = make_observation_fixture(tmp_path)
    assert result.observation is not None
    tampered = copy.deepcopy(result.observation)
    tampered["tree_closure"][0]["entries_digest_sha256"] = "0" * 64

    decision = subject.validate_source_authority(
        registry,
        tampered,
        reviewer_id=subject.POLICY_ENGINE_ID,
        source_relative_path="clean-corporate.md",
        source_bytes=source_bytes["clean-corporate.md"],
        now=FIXED_NOW,
    )

    assert decision.eligible is False
    assert "authority_observation_tree_closure_invalid" in decision.blockers


def test_redirected_origin_request_is_rejected_without_following(
    tmp_path: Path,
) -> None:
    _registry, result, _source_bytes = make_observation_fixture(
        tmp_path, redirect_commit=True
    )

    assert result.ok is False
    assert "authority_origin_redirect_not_allowed" in result.blockers


def test_unattested_injected_transport_is_rejected(tmp_path: Path) -> None:
    _registry, result, _source_bytes = make_observation_fixture(
        tmp_path,
        allow_injected_test_transport=False,
    )

    assert result.ok is False
    assert result.blockers == ("authority_origin_transport_untrusted",)


def test_oversized_origin_response_is_rejected(tmp_path: Path) -> None:
    _registry, result, _source_bytes = make_observation_fixture(
        tmp_path,
        oversized_commit_response=True,
    )

    assert result.ok is False
    assert "authority_origin_response_too_large" in result.blockers


def test_incomplete_tree_closure_is_rejected(tmp_path: Path) -> None:
    _registry, result, _source_bytes = make_observation_fixture(
        tmp_path, incomplete_source_tree=True
    )

    assert result.ok is False
    assert (
        f"authority_tree_incomplete:{subject.PINNED_SOURCE_TREE_PATH}"
        in result.blockers
    )


def test_non_ascii_git_mode_is_rejected_without_crashing(tmp_path: Path) -> None:
    _registry, result, _source_bytes = make_observation_fixture(
        tmp_path,
        malformed_tree_mode=True,
    )

    assert result.ok is False
    assert "authority_tree_entry_invalid:." in result.blockers


def test_path_level_license_override_is_rejected(tmp_path: Path) -> None:
    _registry, result, _source_bytes = make_observation_fixture(
        tmp_path, path_license_override=True
    )

    assert result.ok is False
    assert "authority_path_license_override" in result.blockers


def test_contrary_file_level_license_blocks_coverage(tmp_path: Path) -> None:
    registry, result, source_bytes = make_observation_fixture(
        tmp_path, contrary_spdx=True
    )
    assert result.observation is not None

    decision = subject.validate_source_authority(
        registry,
        result.observation,
        reviewer_id=subject.POLICY_ENGINE_ID,
        source_relative_path="clean-corporate.md",
        source_bytes=source_bytes["clean-corporate.md"],
        now=FIXED_NOW,
    )

    assert decision.eligible is False
    assert decision.blockers == ("authority_source_contrary_spdx",)


@pytest.mark.parametrize(
    ("metadata", "expected_blocker"),
    [
        (
            b"Copyright 2026 Example. All rights reserved.\n",
            "authority_source_contrary_rights_reservation",
        ),
        (
            b"NOTICE: preserve a separate vendor notice\n",
            "authority_source_unresolved_notice",
        ),
        (b"License: GPL-3.0-only\n", "authority_source_contrary_license_metadata"),
    ],
)
def test_contrary_file_metadata_blocks_coverage(
    tmp_path: Path,
    metadata: bytes,
    expected_blocker: str,
) -> None:
    registry, result, source_bytes = make_observation_fixture(
        tmp_path,
        source_metadata=metadata,
    )
    assert result.observation is not None

    decision = subject.validate_source_authority(
        registry,
        result.observation,
        reviewer_id=subject.POLICY_ENGINE_ID,
        source_relative_path="clean-corporate.md",
        source_bytes=source_bytes["clean-corporate.md"],
        now=FIXED_NOW,
    )

    assert decision.eligible is False
    assert expected_blocker in decision.blockers


def test_manual_or_human_reviewer_assertion_is_unsupported(tmp_path: Path) -> None:
    registry, result, source_bytes = make_observation_fixture(tmp_path)
    assert result.observation is not None

    decision = subject.validate_source_authority(
        registry,
        result.observation,
        reviewer_id="manual-human-reviewer",
        authority_basis="manual_assertion",
        source_relative_path="clean-corporate.md",
        source_bytes=source_bytes["clean-corporate.md"],
        now=FIXED_NOW,
    )

    assert decision.eligible is False
    assert "authority_manual_assertion_unsupported" in decision.blockers
    assert "authority_reviewer_unsupported" in decision.blockers


def test_registry_cannot_redirect_the_observer_to_another_origin(
    tmp_path: Path,
) -> None:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    payload["repository"]["api_origin"] = "https://example.invalid"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    registry, blockers = subject.load_trust_registry(path)

    assert registry is None
    assert blockers == ["authority_registry_repository_untrusted"]


def make_observation_fixture(
    tmp_path: Path,
    *,
    contrary_spdx: bool = False,
    redirect_commit: bool = False,
    incomplete_source_tree: bool = False,
    path_license_override: bool = False,
    source_metadata: bytes = b"",
    allow_injected_test_transport: bool = True,
    oversized_commit_response: bool = False,
    malformed_tree_mode: bool = False,
) -> tuple[
    subject.LoadedTrustRegistry, subject.OriginObservationResult, dict[str, bytes]
]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    source_bytes: dict[str, bytes] = {}
    for row in payload["subject"]["sources"]:
        relative_path = row["relative_path"]
        data = f"# {relative_path}\nSynthetic palette metadata.\n".encode()
        if contrary_spdx and relative_path == "clean-corporate.md":
            data += b"SPDX-License-Identifier: GPL-3.0-only\n"
        if source_metadata and relative_path == "clean-corporate.md":
            data += source_metadata
        source_bytes[relative_path] = data
        row["size_bytes"] = len(data)
        row["git_blob_sha1"] = subject.git_blob_sha1(data)
        row["sha256"] = subject.sha256_bytes(data)

    license_bytes = (
        b"Apache License\nVersion 2.0, January 2004\nSynthetic offline fixture.\n"
    )
    payload["license_policy"]["license_blob_sha1"] = subject.git_blob_sha1(
        license_bytes
    )
    payload["license_policy"]["license_sha256"] = subject.sha256_bytes(license_bytes)
    payload["license_policy"]["license_size_bytes"] = len(license_bytes)

    palettes_entries = [
        tree_entry(row["relative_path"], "100644", "blob", row["git_blob_sha1"])
        for row in payload["subject"]["sources"]
    ]
    palettes_tree_sha = subject.git_tree_sha1(palettes_entries)
    hyperframes_entries = [tree_entry("palettes", "040000", "tree", palettes_tree_sha)]
    if path_license_override:
        hyperframes_entries.append(
            tree_entry("LICENSE.local", "100644", "blob", "b" * 40)
        )
    hyperframes_tree_sha = subject.git_tree_sha1(hyperframes_entries)
    skills_entries = [tree_entry("hyperframes", "040000", "tree", hyperframes_tree_sha)]
    skills_tree_sha = subject.git_tree_sha1(skills_entries)
    root_entries = [
        tree_entry(
            "LICENSE",
            "100644",
            "blob",
            payload["license_policy"]["license_blob_sha1"],
        ),
        tree_entry("README.md", "100644", "blob", "a" * 40),
        tree_entry("skills", "040000", "tree", skills_tree_sha),
    ]
    root_tree_sha = subject.git_tree_sha1(root_entries)
    payload["subject"]["root_tree_sha1"] = root_tree_sha
    payload["subject"]["tree_chain"] = [
        {"path": "skills", "git_tree_sha1": skills_tree_sha},
        {"path": "skills/hyperframes", "git_tree_sha1": hyperframes_tree_sha},
        {"path": subject.PINNED_SOURCE_TREE_PATH, "git_tree_sha1": palettes_tree_sha},
    ]

    registry_path = tmp_path / "trust-registry.json"
    registry_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    registry, blockers = subject.load_trust_registry(registry_path)
    assert blockers == []
    assert registry is not None

    tree_payloads: dict[str, dict[str, Any]] = {
        root_tree_sha: {
            "sha": root_tree_sha,
            "truncated": False,
            "tree": root_entries,
        },
        skills_tree_sha: {
            "sha": skills_tree_sha,
            "truncated": False,
            "tree": skills_entries,
        },
        hyperframes_tree_sha: {
            "sha": hyperframes_tree_sha,
            "truncated": False,
            "tree": hyperframes_entries,
        },
        palettes_tree_sha: {
            "sha": palettes_tree_sha,
            "truncated": incomplete_source_tree,
            "tree": palettes_entries,
        },
    }
    if malformed_tree_mode:
        tree_payloads[root_tree_sha]["tree"][0]["mode"] = "💥"

    blobs = {
        payload["license_policy"]["license_blob_sha1"]: license_bytes,
        **{subject.git_blob_sha1(data): data for data in source_bytes.values()},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        assert request.url.host == "api.github.com"
        assert (
            request.extensions["timeout"]["read"]
            == subject.GITHUB_REQUEST_TIMEOUT_SECONDS
        )
        prefix = "/repos/heygen-com/hyperframes/git/"
        assert request.url.path.startswith(prefix)
        suffix = request.url.path.removeprefix(prefix)
        if suffix.startswith("commits/"):
            if oversized_commit_response:
                return httpx.Response(
                    200,
                    content=b"{}",
                    headers={
                        "content-length": str(subject.MAX_GITHUB_RESPONSE_BYTES + 1)
                    },
                )
            if redirect_commit:
                return httpx.Response(
                    302, headers={"location": "https://example.invalid/forged"}
                )
            return httpx.Response(
                200,
                json={
                    "sha": subject.PINNED_SUBJECT_REVISION,
                    "tree": {"sha": root_tree_sha},
                },
            )
        if suffix.startswith("trees/"):
            return httpx.Response(
                200, json=tree_payloads[suffix.removeprefix("trees/")]
            )
        if suffix.startswith("blobs/"):
            blob_sha = suffix.removeprefix("blobs/")
            data = blobs[blob_sha]
            return httpx.Response(
                200,
                json={
                    "sha": blob_sha,
                    "size": len(data),
                    "encoding": "base64",
                    "content": base64.b64encode(data).decode("ascii"),
                },
            )
        raise AssertionError(request.url.path)

    with httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        result = subject.observe_github_git_data(
            registry,
            http_client=client,
            observed_at=FIXED_NOW,
            allow_injected_test_transport=allow_injected_test_transport,
        )
    return registry, result, source_bytes


def tree_entry(path: str, mode: str, item_type: str, sha: str) -> dict[str, str]:
    return {"path": path, "mode": mode, "type": item_type, "sha": sha}
