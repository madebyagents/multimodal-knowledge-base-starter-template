from __future__ import annotations

from app.dante_visual.manifest import VisualAsset
from app.dante_visual.orchestrator import (
    AnalysisRole,
    MockVisionAnalysisProvider,
    ProviderPreflight,
    RoleOutput,
    generate_cards,
    select_premium_assets,
)


def asset(image_id: str = "aftersun-2022-001", sha_prefix: str = "1e") -> VisualAsset:
    return VisualAsset(
        row_number=2,
        image_id=image_id,
        old_relative_path=f"film-stills/aftersun-2022/{image_id}.jpg",
        new_relative_path=f"film-stills/aftersun-2022/{image_id}.jpg",
        previous_relative_path=f"film-stills/aftersun-2022/{image_id}.jpg",
        sha256=sha_prefix + ("a" * 62),
        bytes=1234,
        category="film-stills",
        group="aftersun-2022",
        batch_or_note="",
        width=1920,
        height=1080,
        file_name=f"{image_id}.jpg",
        file_stem=image_id,
    )


def test_mock_provider_preflight_is_execute_ready_without_cloud() -> None:
    preflight = MockVisionAnalysisProvider().preflight()

    assert preflight.execute_ready
    assert preflight.estimated_cost_per_image_usd == 0.0
    assert preflight.data_sent == []


def test_generate_cards_writes_premium_sample(tmp_path) -> None:
    result = generate_cards(
        [asset()],
        cards_root=tmp_path / "cards",
        raw_runs_root=tmp_path / "raw-runs",
        run_id="visual-test",
        provider=MockVisionAnalysisProvider(),
        max_premium=1,
    )

    assert result["cards_written"] == 1
    assert result["premium_selected"] == 1
    assert (tmp_path / "cards" / "film-stills" / "aftersun-2022" / "aftersun-2022-001.json").exists()
    assert (
        tmp_path
        / "raw-runs"
        / "visual-test"
        / "judge"
        / "film-stills"
        / "aftersun-2022"
        / "aftersun-2022-001.json"
    ).exists()


def test_select_premium_assets_fills_requested_budget() -> None:
    selected = select_premium_assets([asset(sha_prefix="01")], max_premium=1)

    assert selected == {"aftersun-2022-001"}


class ObjectScoreProvider(MockVisionAnalysisProvider):
    def analyze(self, asset, roles: list[AnalysisRole]) -> list[RoleOutput]:
        return [
            RoleOutput(
                role=AnalysisRole.JUDGE,
                provider="test",
                model="test",
                confidence=0.9,
                normalized_fields={"score": {"value": "73", "missing_reason": None}, "tier": {"value": "reference"}},
                editorial_flags=[],
                redacted_raw={
                    "provider": "test",
                    "model": "test",
                    "role": AnalysisRole.JUDGE.value,
                    "image_id": asset.image_id,
                    "source_sha256": asset.sha256,
                    "redacted": True,
                },
            )
        ]


def test_generate_cards_accepts_object_shaped_judge_score(tmp_path) -> None:
    result = generate_cards(
        [asset()],
        cards_root=tmp_path / "cards",
        raw_runs_root=tmp_path / "raw-runs",
        run_id="visual-test",
        provider=ObjectScoreProvider(),
        max_premium=0,
    )

    assert result["cards_written"] == 1


class NotReadyProvider(MockVisionAnalysisProvider):
    def preflight(self) -> ProviderPreflight:
        return ProviderPreflight(
            provider="blocked",
            model="blocked-model",
            credentials_present=False,
            execute_supported=False,
            no_training_or_retention="unknown",
            data_sent=["image"],
            estimated_cost_per_image_usd=None,
            disabled_roles=[],
            privacy_posture_known=False,
        )


def test_generate_cards_blocks_not_ready_provider(tmp_path) -> None:
    try:
        generate_cards(
            [asset()],
            cards_root=tmp_path / "cards",
            raw_runs_root=tmp_path / "raw-runs",
            run_id="visual-test",
            provider=NotReadyProvider(),
        )
    except RuntimeError as exc:
        assert "not execute-ready" in str(exc)
    else:
        raise AssertionError("generate_cards should block a provider that is not execute-ready")


class UnsafeRawProvider(MockVisionAnalysisProvider):
    def analyze(self, asset, roles: list[AnalysisRole]) -> list[RoleOutput]:
        return [
            RoleOutput(
                role=AnalysisRole.TECHNICAL,
                provider="unsafe",
                model="unsafe",
                confidence=0.1,
                normalized_fields={},
                editorial_flags=[],
                redacted_raw={"provider": "unsafe", "model": "unsafe", "api_key": "secret", "redacted": True},
            )
        ]


def test_generate_cards_rejects_unredacted_raw_payload(tmp_path) -> None:
    try:
        generate_cards(
            [asset()],
            cards_root=tmp_path / "cards",
            raw_runs_root=tmp_path / "raw-runs",
            run_id="visual-test",
            provider=UnsafeRawProvider(),
        )
    except ValueError as exc:
        assert "disallowed keys" in str(exc)
    else:
        raise AssertionError("generate_cards should reject unsafe raw payload keys")
