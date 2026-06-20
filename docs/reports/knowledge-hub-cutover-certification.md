# Knowledge Hub Cutover Certification

- Run id: `kh-native-image-query-final5-20260620T062441Z`
- Generated at: `2026-06-20T06:24:55.503630+00:00`
- Final score: `0.9947` / gate `0.89`
- Decision: `go_ready_waiting_for_go`
- Recommendation: GO-ready for KH-native reads with Chroma fallback disabled.

## Baseline

- DanteDash rows: `8099`
- DanteDash modalities: `{"image": 2231, "text": 4187, "video": 1681}`
- Chroma to KH relationships: `{"matched": 8099}`
- Runtime fallback enabled: `False`
- KH active visual collection: `visual_memory__voyage_multimodal_3_5_1024`
- KH active visual points: `9849`
- KH visual manifest assets: `9853` across `13` manifests

## Score Dimensions

| Dimension | Weight | Score |
|---|---:|---:|
| inventory_coverage | 0.16 | 1.0000 |
| package_integrity | 0.14 | 1.0000 |
| vector_provenance | 0.10 | 1.0000 |
| search_parity | 0.16 | 0.9667 |
| preview_dto_library_stats | 0.12 | 1.0000 |
| chat_context_sources | 0.12 | 1.0000 |
| dual_fallback_independence | 0.10 | 1.0000 |
| safety_no_leak | 0.10 | 1.0000 |

## Hard Caps And Blockers

- Hard cap: `None`
- Hard cap reasons: `none`
- Blockers: `none`

## Query Suite

| Stratum | Chroma | KH | Recall | Passed |
|---|---:|---:|---:|---|
| explicit_image_id | 5 | 5 | 1.0000 | True |
| semantic_visual | 5 | 5 | 1.0000 | True |
| film_style | 5 | 5 | 1.0000 | True |
| decoupage_language | 5 | 5 | 1.0000 | True |
| video_keyframe | 5 | 5 | 1.0000 | True |
| image_query_sample_1 | 5 | 5 | 0.8000 | True |

## Import Finding

- Official full sync available: `True`
- Granular DanteDash package import available: `True`
- Verified Chroma vector reuse path available: `True`
- Mutation performed in this certification: `True`

## Next Actions

- none
