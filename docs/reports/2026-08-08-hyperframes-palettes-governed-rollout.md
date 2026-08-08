# HyperFrames Palettes Governed Rollout Report

## Decision

- P0 evidence production: `complete`
- P0 terminal state: `blocked_no_mutation`
- P1 status: `no_go`
- LightRAG candidate status: `not_started`
- Knowledge Hub promotion status: `no_go`
- Governed P1 authorization: `authorized=false`, `separately_reviewed=false`,
  `controller_ready=false`
- Provider calls: `0`
- Source writes: `0`
- Datastore writes: `0`

The bounded HyperFrames palette corpus is rights-eligible and passes its frozen
read-only value evaluation. It is not mutation-ready. The deployed LightRAG and
Knowledge Hub surfaces do not expose the deployment-bound identity, fencing,
atomicity, lease, closure, and restart guarantees required by the governed
contract. The budget is intentionally inactive and legacy identity
reconciliation is not green. The canonical result is therefore
`blocked_no_mutation`; no one/five/topic/full mutation stage ran.

Knowledge Hub remained closed. No active graph, index, manifest, database,
Qdrant collection, source file, or provider state was changed.

## Immutable Subject And Evidence Generation

| Field | Value |
|---|---|
| Subject revision | `f763c5481744ac775a4685f2af31148254b529d2` |
| Executable-tree digest | `a171d1d50d0e45b7ae9bfaea738148927a367371b3dc797d87fc6ca97c44cac1` |
| Subject binding | `verified` in both runs |
| Evidence generation | `hyperframes-palettes-20260808-v2` |
| Observation time | `2026-08-08T12:02:53Z` |
| Generated targets | `18` |
| Generation aggregate SHA-256 | `ce8fffbd735aa863d54b2bbead64ef49f165a91cc4ac15cb8b408f36447b4d0b` |
| Policy SHA-256 | `623b8108992abeb77e8a1f10341770875e8585d59658e65eafd0bee8495f8c38` |
| Runtime-capability SHA-256 | `eb216ac4e360807f5f3f28145e89f9ba84c72d8622ed386dccdcd769ac942b98` |

The subject commit and its working-tree recomputation produced the same
executable-tree digest before evidence publication. The policy was written
last and hash-binds the authority, origin observation, public license, nine
source-specific rights decisions, holdout, value evidence, and runtime
capability observation.

Primary evidence hashes:

- authority: `164e371ecfe9bea291efb76e752205dfd02fc5ded9ea60389d78ce1850f36db9`;
- origin observation: `20d07f53e35026e4ea09185f4745267bda88296c295c606e16d7d0d2c171a261`;
- Apache-2.0 license: `4259155fb06f127687ee7b0a8a3682d45132db0f2da26cbc0b7a2d1e796436b8`;
- holdout artifact: `cff1fb642bfdf5540f099c9a2eefc92ab0823e61d9cc0002056696af29a356a6`;
- value certificate: `e9212d305fcc6349f1cba6cb9b46e63d4e49c463e21c8fca036288c456ca838d`;
- value preflight: `9c74c7116befdbb8ae55945cc7df9f55dd868cbd2719a7a9fdc6560ed51d5f2a`;
- value artifact manifest: `eaaf6004feff2c1988f5ce329c65f7e6df03c9090222acf637bb0d0c03f4e55e`.

## Corpus And Rights Result

| Result | Value |
|---|---:|
| Markdown sources | 9 |
| Total source bytes | 3,646 |
| Eligible sources | 9 |
| Blocked or unknown sources | 0 |
| Source-specific rights records | 9 |
| Cards / normalized records | 9 / 9 |
| Public leaks | 0 |

Inventory audit digest:
`e77e9bd5444e9b3df16db85c32a848e26621d3cad1d94d859e2b01415d97299c`.

Every source was verified against the pinned official HyperFrames commit
`2935be6bf66d12f41ac768d841d567323b547357`, its complete Git tree/blob
closure, the repository-root Apache-2.0 license, and the subject-bound trust
registry. The exact local source documents were read only and were not copied
into repository or run artifacts. This is a governed evidence-sufficiency
decision, not legal advice.

## Value And Holdout Result

The four frozen baseline searches all returned zero results and the curated
metadata covers all four observed palette-routing needs. The candidate passed
five of five routing checks, five of five answer-criteria checks, and one of one
negative control, with zero unsupported current claims, raw-source-body leaks,
invented evidence claims, provider calls, or incremental evaluation cost.

Holdout digest:
`5866518d046a8825ad8868e98cd8c9e6ffe76706fc83dce550bf87ce525359cf`.

The validator recomputed the fixed baseline request hashes, empty-response
hash, dashboard statistics, holdout membership, candidate metrics, thresholds,
zero-call cost, and no-body-persistence claim from the hash-bound preflight.
Self-attested or weakened evidence fails closed.

## Exact Stage Contract

| Stage | Frozen membership | Governed result |
|---|---|---|
| One-document | `clean-corporate.md` | `blocked_until_p0_green` |
| Five-document cumulative | `clean-corporate.md`, `bold-energetic.md`, `dark-premium.md`, `pastel-soft.md`, `warm-editorial.md` | `blocked_until_p0_green` |
| Topic cluster `chromatic-expression` | `bold-energetic.md`, `jewel-rich.md`, `neon-electric.md`, `pastel-soft.md` | `blocked_until_p0_green` |
| Full-corpus remainder | `monochrome.md`, `nature-earth.md` | `blocked_p0_only` |

The partition covers all nine sources exactly. Gate 2 contains four new source
identities after Gate 1. The topic cluster has two new members after Gate 2 and
requires two relationship patterns; existing members are no-ops. These are
validated selection contracts, not evidence that a remote mutation occurred.

## Independent Gate Vector

| Gate | Status | Downstream permission |
|---|---|---|
| Inventory | `pass` | P0 dry-run allowed |
| Rights | `pass` | P0 dry-run allowed |
| Value | `pass` | P0 dry-run allowed |
| Dependency closure | `pass` | P0 dry-run allowed |
| Leak scan | `pass` | P0 dry-run allowed |
| Budget | `no_go` | External processing denied |
| Legacy reconciliation | `blocked` | P0 terminal readiness denied |
| LightRAG mutation | `blocked` | Mutation denied |
| Knowledge Hub promotion | `no_go` | Promotion denied |

Canonical blocker set:

- LightRAG: `lightrag.authoritative_payload_hash_lookup`,
  `lightrag.executable_fingerprint_missing`,
  `lightrag.legacy_identity_reconciliation`, `lightrag.server_epoch_missing`,
  `lightrag.service_enforced_fencing`, `lightrag.service_identity_missing`,
  `lightrag.service_version_missing`, `lightrag_capability_policy_not_green`,
  and `lightrag_capability_legacy_reconciliation_not_green`.
- Knowledge Hub: `knowledge_hub.atomic_import`,
  `knowledge_hub.executable_fingerprint_missing`, `knowledge_hub.gate_close`,
  `knowledge_hub.openapi_fingerprint_missing`,
  `knowledge_hub.openapi_unavailable`, `knowledge_hub.restart`,
  `knowledge_hub.server_epoch_missing`, `knowledge_hub.service_identity_missing`,
  `knowledge_hub.single_use_capability`,
  `knowledge_hub.watchdog_or_lease_ttl`, and
  `knowledge_hub_capability_policy_not_green`.
- Budget: `budget_contract_not_active`, `budget_reservation_missing`,
  `budget_authorization_incomplete`, `budget_authorization_not_current`,
  `budget_disclosure_contract_incomplete`,
  `budget_provider_rate_basis_incomplete`, and
  `budget_total_ceiling_not_positive`.
- Legacy: `legacy_reconciliation_not_green`.

## Two-Run Determinism Certification

Fresh run IDs:

- `hyperframes-palettes-governed-20260808-a`
- `hyperframes-palettes-governed-20260808-b`

Both runs produced exactly 17 regular artifacts with no missing or extra
members. Canonical normalization was limited to the enumerated run-local ID
fields. The comparator recorded the first run's raw hashes, compared the second
run, and re-read the first run to prove it remained immutable.

Canonical aggregate SHA-256:
`8d93bd4eea3f857c348853f8dd7216be0978505e0b065fc8a5a619b4ff4a6fb1`.

Each run certified:

| Result | Value |
|---|---:|
| Terminal state | `blocked_no_mutation` |
| Sources / eligible / blocked | 9 / 9 / 0 |
| Cards / eval queries | 9 / 5 |
| LightRAG planned rows | 0 of 9 |
| Knowledge Hub plan rows | 18, all non-mutating |
| Provider calls | 0 |
| Source / datastore writes | 0 / 0 |
| Public leaks | 0 |

Run-local certification hashes:

| Run | Black Label certification | P0-P8 certification | Phase ledger |
|---|---|---|---|
| A | `7a4e0bf544e3f1aebd46dab14fe86157ab8ea6f024204311b1a344e44f32c1c1` | `07a9ae546a1abf8a18669bf5b67f46601800679f8921b733c476830c9fd6fb4c` | `62b4da8681482fe13490699d42bca02ef74cf0b5e729acf75e7dbce30df2817d` |
| B | `e099edeb7932d947c186bd8fcc07566637c7c1368f482b1e84d027f5de0d6fda` | `7188f3c0f647f36718e3ee024eeee9ca7fdf2b67d826213ad7b58b2b46b4eb09` | `792156ce2be7faf4e2de81c03c18147b9e997420cfbaba1afd0aee2c23da0e49` |

## Verification And Review

- Focused governed rollout suite: `126 passed`.
- Full backend suite: `493 passed`, with six dependency deprecation warnings.
- Ruff on all changed Python files: `All checks passed!`.
- `git diff --check`: passed.
- Frontend: `pnpm typecheck` and `pnpm build` passed; the existing large-chunk
  advisory remains non-blocking.
- Multi-agent LFG review: correctness, coherence, and simplicity passes found no
  remaining P0/P1 defect after the final fixes.
- Pull request: draft PR
  [#4](https://github.com/madebyagents/multimodal-knowledge-base-starter-template/pull/4),
  open against `main`; no remote checks are configured.

## Delivery Boundary And Next Safe Step

The reviewed subject is immutable. The carrier may contain only the generated
policy, runtime-capability manifest, HyperFrames evidence directory, this
report, and the runbook update. Its revision is recorded externally after the
carrier commit because a commit cannot hash-bind its own SHA.

The next safe step is external service work: add deployment-bound LightRAG
payload identity, durable single-use fencing and receipts, plus Knowledge Hub
candidate generations, atomic swap, lease/watchdog, gate closure, and typed
restart. Then issue a separately reviewed budget authorization, rerun the
capability producer, and begin the frozen one/five/topic/full mutation stages.
Until those conditions are proven, the truthful state remains P0
`blocked_no_mutation`, P1 `no_go`, and the overall promoted rollout incomplete.
