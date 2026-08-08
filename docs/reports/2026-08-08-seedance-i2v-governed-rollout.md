# Seedance I2V Governed Rollout Report

## Decision

- P0 status: `blocked_no_mutation`
- P1 status: `no_go`
- LightRAG candidate status: `not_started`
- Knowledge Hub promotion status: `not_started`
- Governed P1 authorization: `authorized=false`, `separately_reviewed=false`, `controller_ready=false`
- Provider calls: `0`
- Source writes: `0`
- Datastore writes: `0`

P0 is blocked because all 21 sources remain `rights_status=unknown`. No source
has explicit, hash-bound permission for both local embedding and derived
summaries, so the eligible set is empty. The P0 milestone requires at least one
eligible, value-bearing card and therefore cannot be green.

P1 did not run and is not complete. No provider preflight, checkpoint, LightRAG
stage, candidate freeze, Knowledge Hub dry-run, gate open, import, restart, or
promotion occurred.

## Scope And Safety

This report covers a read-only source audit and the repository P0 delivery candidate.
The source root was not changed. The audit made no provider request and performed
no LightRAG, Knowledge Hub, vector-store, database, graph, or source mutation.

Repository evidence contains corpus-relative paths, stable IDs, public-safe
hashes, counts, redacted decisions, and bounded independently authored policy
metadata. It excludes verbatim source bodies, PNG bytes, credentials, private
endpoint values, raw provider payloads, account data, sessions, and absolute
source or runtime paths.

## Frozen Corpus Evidence

| Field | Value |
|---|---:|
| Markdown sources | 17 |
| PNG sources | 4 |
| Total sources | 21 |
| Markdown bytes | 90,822 |
| PNG bytes | 3,297,861 |
| Total bytes | 3,388,683 |
| Eligible sources | 0 |
| Unknown-rights sources | 21 |
| External-processing-enabled sources | 0 |

Inventory audit digest:
`38ca2330651ce290da8d97b1d1cb8b2a11ce83161687013af32ac83ede6b40e3`

The digest is SHA-256 over the sorted sequence
`relative_path<TAB>size_bytes<TAB>source_sha256<LF>`. The full sorted inventory,
per-source sizes and hashes, stable IDs, topic IDs, card roles, risk ranks, and
rights decisions are frozen in
`backend/app/dante_visual/manifests/seedance_i2v_corpus_20260808.v1.json`.

## Rights-Class Adjudication

| Class | Sources | Evidence present | Missing proof | Decision |
|---|---:|---|---|---|
| Operator-local empirical text | 4 | Origin and experiment provenance | Hash-bound authority plus explicit embedding and derived-summary grants | `unknown` |
| NotebookLM and web-derived text | 3 | Notebook/task identifiers and URL map | Source licenses, capture hashes, authority, and local-use grants | `unknown` |
| ChatGPT-connect derived text | 8 | Bundle identifiers, source-relative bundle paths, and promotion metadata | Input rights and explicit local-use predicates | `unknown` |
| ModelArk-generated visuals | 4 | Hash-identical copies of declared experiment outputs | Output-use terms, asset or likeness attestation, and local-use grants | `unknown` |
| Compiled packs | 2 | Upstream relationships | Clear rights for every contributing input | `unknown` |

This is an evidence-sufficiency decision for the rollout contract, not a broad
legal conclusion. Provenance, byte identity, workflow promotion, or an earlier
operator GO does not silently grant local embedding, derived-summary, provider
disclosure, or redistribution rights.

## Topic, Role, And Risk Policy

Every source has one deterministic `topic_id`, one `card_role`, and a unique
numeric `risk_rank` from 1 through 21. The declared topics are:

- `ark_moderation_safety`
- `i2v_operator_overview`
- `ark_lowmod_controlled_ab`
- `video_model_current_state`
- `retrieval_governance`
- `i2v_motion_control`
- `research_provenance`

Declared roles are `source_card`, `concept_card`, `relation_card`,
`visual_evidence_card`, `craft_application_card`, and `retrieval_eval_card`.
Lower numeric rank means higher review risk. Volatile research synthesis and
compiled current-state packs rank highest; eval-only cards rank lowest for apply
selection. These labels do not override rights eligibility.

## Value And Holdout Contract

The value hypothesis is that a rights-cleared curated subset would improve
operator retrieval for motion control, keyframe strategy, multi-shot continuity,
evidence-bounded model selection, and controlled ModelArk experiment findings
without increasing stale claims or invented evidence.

The independent H1-H8 holdout was authored from operator-facing source intent,
not generated cards, and frozen before card generation. Holdout digest:
`9644d427c7be45246f3f3399b52ade4ae35584583e828e3e692f18a330e00c72`.

Required candidate thresholds are:

- 8 of 8 topic-routing checks;
- at least 7 of 8 answer-criteria checks;
- 2 of 2 negative controls;
- zero unsupported current claims;
- zero raw source-body leaks;
- zero invented evidence claims;
- at least `0.125` absolute answer-pass improvement over baseline;
- irrelevant-hit rate at 5 no greater than `0.2`.

Baseline snapshot: `PENDING_NOT_CAPTURED`

Candidate evaluation: `PENDING_NO_ELIGIBLE_CANDIDATE`

Because the baseline is not captured and no source is eligible, the value gate is
not green and does not authorize mutation.

## Budget And Capability State

The budget contract is `inactive_blocked`. It permits zero calls, zero tokens,
zero source-derived fields, and a total ceiling of zero. It has no operator-
instruction hash, issue time, expiry, reservation, or materialized rate basis.
It cannot be used as provider authorization.

| Capability surface | Audit state | Eligibility |
|---|---|---|
| LightRAG immutable payload lookup and service fencing | `audited_blocked` | mutation false |
| Knowledge Hub atomic import and single-use promotion controls | `audited_blocked` | promotion false |
| Legacy identity reconciliation across all 21 sources | `not_provable` | mutation blocked |

The redacted read-only LightRAG audit scanned 15,768 document records. All had a
document ID and `file_source`, but none exposed an authoritative payload hash,
normalized fingerprint, embedded source hash, or Knowledge Hub reference. The
legacy term probe found no obvious candidate, but the missing identity evidence
means absence is not proven. The advertised insertion contract also lacks a
payload-hash and fencing or lease field.

The Knowledge Hub audit observed available health and import-route discovery but
could not prove atomic candidate commit. It found no advertised single-use
authorization, watchdog or lease TTL, typed gate-close, or restart control.
Those promotion blockers are independent, while the LightRAG capability and
rights blockers stop before any P1 stage.

The shared redacted capability evidence is
`backend/app/dante_visual/manifests/seedance_i2v_runtime_capabilities_20260808.v1.json`,
SHA-256
`83a0ee837dca826de87cabb34dbf05bc86a9d500008f803702f42b8b3a405ba2`.

## Machine P0 Dry-Run Evidence

The final reviewed dry-run is `seedance-i2v-p0-20260808-final9`. It exited `2`
because the governed result is blocked, not because generation failed. It
created 17 owner-only runtime artifacts and certified:

| Result | Value |
|---|---:|
| Terminal state | `blocked_no_mutation` |
| Certification blockers | 41 |
| Sources / assets / cards | 21 / 21 / 21 |
| Eligible / blocked sources | 0 / 21 |
| LightRAG planned rows | 0 of 21 |
| Knowledge Hub plan rows | 42, all non-mutating |
| Visual requests | 4 metadata-only rows |
| Eval queries | 8 |
| Provider calls | 0 |
| Source / datastore writes | 0 / 0 |
| Public leaks | 0 |

The complete 17-file run digest is
`65fb127b82109176ad113bfba8e6b697c44a7b87d5427bc400f9f49514c992fd`.
It is the canonical `stable_hash` of the sorted mapping from artifact basename
to that artifact's SHA-256, so it can be recomputed without embedding the run
directory path.
The 13 run-independent data artifacts are byte-identical across two fresh run
IDs and have aggregate SHA-256
`84bb5342e54921f16705ce3b6a8dd854b1c00d1cc90f8ab20119f67f731bd03f`
under the same basename-to-SHA-256 mapping algorithm.
The four expected run-bound differences are the two certifications, phase
ledger, and human report.

Leak verification found zero absolute source-root references and zero matches
across 920 non-overlapping 96-character source-body chunks. It also found zero
holdout rows requiring redaction after
the two unsafe verbatim prompts were replaced and the holdout refrozen. The run
directory mode is `0700`.

Machine hashes:

- policy manifest: `e06d457384197e3981749c6fa5c6c1d2754cb3a2a15e302f9f50865d97b0d88c`;
- Black Label certification: `93d1ee9c66813897f09115adbc9995be8d7596cc20830b2e01e11f34eed328e3`;
- P0-P8 compatibility certification: `10d9d1f0386d11ec698b8ae59620be55cd19d62c7e3d337312a218737db3a29b`;
- phase ledger: `6de65b7fdcd3602a46998f2bc43e14dba0a287817258f187db576ac56700946e`.

## Gate Evidence

| Gate | Status | Evidence or blocker |
|---|---|---|
| Exact inventory | pass | 21 sorted sources and frozen audit digest |
| Rights | blocked | 21 unknown, zero locally eligible |
| Independent baseline | pending | no baseline snapshot |
| Independent holdout definition | pass | H1-H8 frozen and hashed |
| Legacy reconciliation | blocked | read-only indices cannot prove presence or absence by immutable identity |
| LightRAG capability | blocked | authoritative payload hash and service fencing unavailable |
| Public artifact leak scan | pass | 0 public leaks, 0 absolute source-root refs, 0 matching 96-character source chunks |
| Budget authorization | blocked | inactive, zero ceiling |
| Paid provider preflight | no-go | rights, value, capability, and budget prerequisites not met |
| LightRAG Gate 1 | no-go | no eligible source and no mutation contract |
| LightRAG Gate 2 | no-go | Gate 1 not green |
| LightRAG Gate 3 | no-go | Gate 2 not green |
| LightRAG full apply | no-go | sample stages and value gate not green; production adapter has no remote single-use fencing |
| Candidate certification | not started | no full apply or frozen graph |
| Knowledge Hub promotion | not started | read-only capability audit is `audited_blocked`; no candidate certificate, promotion preflight, gate opening, or import occurred |

The dormant P1 controller is also fail-closed at its repository boundary. Gate
2 requires four new distinct source identities after Gate 1 and validates five
cumulative identities before constructing a client. Governed apply requires the
three controller authorizations. Legacy apply additionally requires explicit
operator hashes for both the canonical source certification and the complete
consumed bundle on every build, refresh, migration, and apply command; a mutable
legacy marker or certification hash alone grants no authority. The composite
binding covers the ordered normalized output, crosswalk, CAG candidates, and
referenced text artifacts verified against their declared SHA-256 from one
open descriptor; inode or in-flight content changes fail closed. The
controller also hash-binds the card manifest and apply plan at certification
time and persists the complete generation recipe, including the evaluation
threshold. Before every apply it reloads one
immutable source snapshot, rejects an explicit-versus-certified source mismatch,
canonically rebuilds the cards and plan with that certified recipe, and rejects
any drift before the first insert or any later stage. A redacted legacy alias
can resolve only one exact certification-and-bundle hash match under the
operator-supplied source root.

Every mutation batch now also requires a service-enforced single-use fence bound
to the Black Label certification, stage, input bindings, batch, ordered payload
hashes, file sources, expiry, and nonce, plus a matching remote receipt. A local
exclusive claim protects same-host races and remains after a real or uncertain
mutation. The audited production client exposes no remote fencing method, so it
fails closed before insertion; tests prove one mutation maximum across both
same-host races, independent workspace copies, and independently generated
equivalent runs using a conforming fake service. The certification is rehashed
before claim creation and before every remote fence. A lost response after a
remote commit remains an uncertain attempted mutation with its claim retained,
so automatic replay is blocked.
Pre-binding successful ledgers have an explicit compatibility migration that
canonically regenerates the certified inputs, requires live read-only recovery,
preserves the original ledger bytes, and anchors a single hash-bound sidecar on
every refresh. Canonical rebuilds use a generated contained run ID, not the
historical certification value, and internal failures return public-safe
blockers. There is no automatic legacy downgrade or write replay.

## Delivery Evidence

These fields must be populated only from generated or externally verified
evidence. They must not be inferred from this scaffold:

| Field | Current value |
|---|---|
| Generated dry-run run ID | `seedance-i2v-p0-20260808-final9` |
| Generated dry-run artifact digest | `65fb127b82109176ad113bfba8e6b697c44a7b87d5427bc400f9f49514c992fd` |
| Machine certification digest | `93d1ee9c66813897f09115adbc9995be8d7596cc20830b2e01e11f34eed328e3` |
| Legacy-reconciliation evidence hash | `83a0ee837dca826de87cabb34dbf05bc86a9d500008f803702f42b8b3a405ba2` |
| LightRAG capability-audit evidence hash | `83a0ee837dca826de87cabb34dbf05bc86a9d500008f803702f42b8b3a405ba2` |
| Knowledge Hub capability-audit evidence hash | `83a0ee837dca826de87cabb34dbf05bc86a9d500008f803702f42b8b3a405ba2` |
| Governed P1 authorization | `false / false / false`; legacy mutation guard closed |
| Leak-scan result | `PASS`: 0 leaks, absolute refs, or matches across 920 96-character body chunks |
| Focused test result | `146 passed`; changed Python files Ruff clean |
| Full project test result | `412 passed`, 6 dependency deprecation warnings, using test-only placeholder settings credentials |
| Full-repository Ruff | 3 unrelated pre-existing findings in `kb_gateway.py`, `lightrag_cinema_craft_ingest.py`, and `routes/chat.py` |
| Frontend verification | `pnpm typecheck` and `pnpm build` passed |
| Browser gate | Not executed: no web files/routes changed and `agent-browser` is unavailable |
| Multi-agent review | Security, correctness, and simplicity reviewers all returned clear |
| Executed commit SHA | `a45d669be203b394997a85207c494ba57a9e86e7` |
| Pull request | Draft PR [#4](https://github.com/madebyagents/multimodal-knowledge-base-starter-template/pull/4), open against `main` and stacked on draft PR #3 |
| CI result | No remote checks reported for the branch at finalization time |
| Evidence commit | `docs: finalize governed rollout delivery evidence` on the same branch |
| Final snapshot | `snapshots/DEEP_MEMORY_DANTEDASH_035.md` |

## Rollback Boundary And Next Safe Step

The current rollback boundary is repository-only. No runtime state changed, so no
source, graph, index, database, provider, or Knowledge Hub restoration is needed.

The next safe step is read-only: obtain hash-bound rights records for the intended
local uses, capture the independent baseline, and design or independently prove
the missing immutable-identity, payload-hash, and service-fencing controls.
Revalidate the policy only after those inputs exist. Until then, the truthful
terminal result remains P0 `blocked_no_mutation`, P1 `no_go`, and the overall
rollout incomplete.
