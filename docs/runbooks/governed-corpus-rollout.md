# Governed Corpus Rollout Runbook

This runbook defines the fail-closed operating sequence for a corpus governed by
`backend/app/dante_visual/manifests/seedance_i2v_corpus_20260808.v1.json`.
It separates local inventory and policy validation from paid provider work,
LightRAG mutation, and Knowledge Hub promotion.

## Current Gate State

- P0: `blocked_no_mutation`
- P1: `no_go`
- Inventory: 21 sources accounted for, including 17 Markdown files and four PNGs
- Rights: 21 `unknown`, zero eligible
- External processing: disabled for every source
- Legacy reconciliation: `not_provable` with the deployed read-only indices
- LightRAG mutation capability: audited and blocked
- Knowledge Hub promotion capability: audited and blocked
- Provider calls: zero
- Source, LightRAG, Knowledge Hub, and datastore writes: zero

The current policy is intentionally terminal at P0. Do not run provider
preflight, create a mutation authorization, start a LightRAG stage, or open a
Knowledge Hub import gate. P1 has not started and is not complete.

## Safety Boundary

The source root is a runtime-only, read-only argument. Never record its absolute
path in a committed manifest, report, log summary, command transcript, or pull
request. Repository artifacts may contain corpus-relative paths, stable IDs,
hashes, counts, redacted decisions, and bounded independently authored policy
metadata. They must never contain verbatim source bodies or source binary bytes.

Never persist:

- credentials, tokens, sessions, or environment values;
- private endpoint or proxy values;
- raw provider requests or responses;
- source Markdown bodies or PNG bytes;
- absolute source, checkpoint, or runtime paths;
- account, billing, or provider-console details.

Dry-run means zero provider calls and zero external writes. A command that calls
a provider, mutates LightRAG, opens a Knowledge Hub gate, or writes a datastore is
not a dry-run regardless of its label.

## Governed Artifacts

The committed policy surface is:

- `backend/app/dante_visual/manifests/seedance_i2v_corpus_20260808.v1.json`
- `backend/app/dante_visual/manifests/seedance_i2v_runtime_capabilities_20260808.v1.json`
- `backend/app/dante_visual/manifests/lightrag_multimodal_production_profile_20260807.v1.json`
- `docs/reports/2026-08-08-seedance-i2v-governed-rollout.md`
- this runbook

Generated runtime artifacts belong under an ignored per-run directory. They must
remain outside commits until a redacted evidence summary is deliberately added.
The generated artifact set is expected to include source, rights, package, card,
crosswalk, visual-queue, LightRAG-plan, CAG, eval, phase-ledger, certification,
and human-report outputs. Their presence alone does not certify any gate.

## HyperFrames v2 Evidence Workflow

This is a prospective, read-only P0 workflow. It does not change the current
Seedance gate state, certify a completed HyperFrames run, or authorize P1.

1. **Run Phase 0 value preflight.** Freeze the four palette-selection
   questions and the existing-corpus baseline before corpus-specific work. Stop
   before authority engineering when fewer than two questions expose a real
   retrieval gap. Phase 0 makes no provider calls and authorizes no paid budget.
2. **Freeze the subject.** Review, test, and commit the executable
   implementation and its exact executable-tree digest before collecting live
   evidence. Later evidence must bind to that immutable `subject_revision`.
3. **Generate origin and authority evidence.** Observe the allowlisted official
   HyperFrames origin read-only, verify the pinned commit-to-tree-to-blob
   closure, license bytes, `NOTICE` result, and all nine source bindings, then
   apply the subject-bound license-coverage policy. Generated evidence cannot
   replace the trust roots or self-approve a source.
4. **Run the generic negative capability audit.** Produce the version 2
   LightRAG and Knowledge Hub audit from one stable service epoch. This slice
   may record only `discovered` or `observed` negative evidence; it must reject
   a client-declared `available` or `deployment_bound` result. Missing epoch or
   owning-service attestation remains `no_go`.
5. **Publish one complete evidence generation.** Materialize the Phase 0
   baseline, holdout, origin observation, license, authority, per-source rights,
   and capability evidence first. Write the corpus policy last as the completion
   record that hash-binds the exact generation; missing, extra, stale, or mixed
   inputs block the run.
6. **Create two immutable dry-runs.** Use distinct run IDs and roots over the
   same subject, policy, source inventory, and evidence generation. Never edit
   or normalize either run directory in place, and preserve the first run's raw
   byte hashes across the comparison.
7. **Apply the canonical comparison.** Require exactly the 17 basenames defined
   by `backend/app/governed_run_determinism.py`; missing, extra, symlinked, or
   non-regular members fail. Normalize only `/run_id` and `/source_run` in
   `black-label-certification.json`, `/run_id` in
   `p0-p8-certification.json` and `phase-ledger.json`, and the exact report
   run-ID line. Preserve JSONL row order, canonicalize JSON with sorted keys and
   compact ASCII-safe encoding, hash each artifact with SHA-256, and aggregate
   the sorted basename-to-hash map with `p0p8.stable_hash()`.

The subject commit owns executable behavior. A later carrier may add only the
allowlisted non-executable policy, evidence, report, and runbook paths; its SHA
belongs in the external post-commit delivery envelope. Create and reconcile the
next sequential snapshot only from the canonical workspace after carrier
delivery—never by rewriting this worktree's stale snapshot chain.

Rights eligibility, a green local value result, or equal dry-run digests do not
open P1. LightRAG mutation and Knowledge Hub promotion remain fail-closed until
their owning services provide the required deployment-bound, single-use, and
atomicity guarantees through separately reviewed authorization.

## Shared Agent And Operator CLI

Agents and operators use the same CLI contract; there is no hidden UI-only
mutation path. From `backend`, disable shell tracing and supply the read-only
source root privately. Manifest and artifact arguments are resolved relative to
the repository root even though the Python environment is launched from
`backend`:

```bash
set +x
DANTEDASH_GOVERNED_SOURCE_ROOT="/operator-supplied/read-only/source-root"
export DANTEDASH_GOVERNED_SOURCE_ROOT
uv run python ../scripts/governed_corpus_rollout.py \
  --source-root "${DANTEDASH_GOVERNED_SOURCE_ROOT:?set privately}" \
  --policy-manifest backend/app/dante_visual/manifests/seedance_i2v_corpus_20260808.v1.json \
  --production-profile backend/app/dante_visual/manifests/lightrag_multimodal_production_profile_20260807.v1.json \
  --runtime-capabilities backend/app/dante_visual/manifests/seedance_i2v_runtime_capabilities_20260808.v1.json \
  --artifact-root logs/governed-corpus-rollout
```

Do not pass `--apply`. Omit `--run-id` to generate a collision-resistant ID.
Every run ID is immutable and single-use; a duplicate is rejected without
overwriting its directory. The CLI always prints a public-safe JSON result for a
governed outcome or a recognized invalid/duplicate request. Exit `0` means
`green_dry_run`; exit `2` means blocked with no mutation. A blocked result is a
valid certification outcome, not an execution failure to retry automatically.

## Lifecycle

| Phase | Allowed behavior | Required result before advancing |
|---|---|---|
| P0 inventory | Read allowlisted local files, recompute size and SHA-256, validate policy | Exact sorted inventory and corpus digest |
| P0 rights | Evaluate hash-bound rights evidence without transmitting content | At least one locally eligible source; unknown sources remain visible and blocked |
| P0 value | Capture the independent baseline and evaluate the frozen H1-H8 contract | Value threshold met without unsupported claims or leakage |
| P0 capability | Read-only legacy, LightRAG, and Knowledge Hub audits | LightRAG mutation contract green; Knowledge Hub result recorded separately |
| Paid preflight | Metadata-only auth, billing, host, TLS, redirect, scope, and budget probe | Fresh, bounded, rights-compatible authorization |
| LightRAG stages | One source, five sources, declared topic cluster, then remaining eligible corpus | Signed, fenced, reconciled stage ledgers and a frozen candidate certificate |
| Knowledge Hub promotion | Separate dry-run and single-use promotion transaction | Historical preservation, closed gate, healthy restart, native regressions green |

Advancement is monotonic only when every required input is bound to the same
corpus digest and reviewed executable commit. A later failure does not retroactively
turn an earlier blocked or incomplete phase into success.

## P0 Inventory Gate

Validate the committed JSON without contacting any service:

```bash
jq -e . backend/app/dante_visual/manifests/seedance_i2v_corpus_20260808.v1.json >/dev/null
jq -r '.sources[] | [.relative_path, .size_bytes, .source_sha256] | @tsv' \
  backend/app/dante_visual/manifests/seedance_i2v_corpus_20260808.v1.json
```

For the runtime source root, the inventory implementation must:

1. reject a missing path, path escape, symlink, unsupported extension, or extra file;
2. enumerate only `.md` and `.png` entries from the allowlist;
3. sort by corpus-relative path in bytewise ascending order;
4. recompute every byte size and SHA-256;
5. compute the audit digest over
   `relative_path<TAB>size_bytes<TAB>source_sha256<LF>`;
6. stop on any mismatch before reading a body into a card builder.

The frozen expected audit digest is
`38ca2330651ce290da8d97b1d1cb8b2a11ce83161687013af32ac83ede6b40e3`.
Do not infer successful ingestion from a prior timeout or from the presence or
absence of a single legacy identifier.

## Rights Adjudication Gate

The five source classes are evidence categories, not permission categories:

1. operator-local empirical text;
2. NotebookLM and web-derived text;
3. ChatGPT-connect derived text;
4. ModelArk-generated visual evidence;
5. compiled packs.

For any source to move from `unknown` to a locally eligible status, a reviewer
must provide evidence bound to that exact source hash and prove both
`local_embedding_permission_explicit` and
`derived_summary_permission_explicit`. The record must also prove the granting
party's authority. Provenance, an operator GO from another handoff, a matching
file hash, workflow promotion metadata, or model output ownership assumptions do
not satisfy those predicates by themselves.

External processing is a separate decision. It requires an exact match for
provider, region, source-derived field, use, and evidence hash. Local eligibility
does not imply external disclosure permission. `unknown` and `blocked` entries
remain accounted for and must never silently disappear from certification.

The four PNGs also require preserved generated-output use terms and a registered
asset or likeness attestation before visual embedding or derived visual summaries
can be eligible. Compiled packs inherit the least-permissive status of every
upstream input.

Each eligible source must reference exactly one non-symlink JSON evidence file
relative to the policy manifest. Its SHA-256 must match
`rights_evidence_sha256`, and its schema, source ID/hash, rights state,
permissions, predicates, review date, and reviewer must exactly match the policy
row. A path, hash, schema, or field mismatch is a blocker; an evidence filename
or a 64-character string alone is never proof.

## Value And Independent Holdout Gate

The H1-H8 holdout is frozen in the manifest before card generation. Its digest is
`9644d427c7be45246f3f3399b52ade4ae35584583e828e3e692f18a330e00c72`.
Generated cards, generated exact-recovery queries, and candidate payloads must not
be used to author or modify the expected answers.

Capture the baseline before any candidate card exists. Record the baseline and
candidate separately. The candidate must satisfy all of the following:

- 8 of 8 topic-routing checks;
- at least 7 of 8 answer-criteria checks;
- 2 of 2 negative controls;
- zero unsupported current claims;
- zero raw source-body leaks;
- zero invented evidence claims;
- at least `0.125` absolute answer-pass improvement over baseline;
- irrelevant-hit rate at 5 no greater than `0.2`.

If the baseline already makes a requested gain mathematically impossible, stop
and revise the value contract through review rather than relaxing it at runtime.
Do not treat a generated self-recall eval as independent value evidence.

A `frozen_green` value contract must reference a separate non-symlink candidate
certificate by relative path and SHA-256. That certificate must exactly bind the
candidate metrics, corpus digest, holdout hash, production-profile hash,
runtime-capability hash, evaluated repository revision, and evaluation time. It
must also hash-bind an artifact manifest whose allowlisted files are present and
individually hash-verified. Embedded metric values, a certificate ID, or an
artifact filename without those independently loaded bindings cannot open the
gate.

## Budget And Provider Preflight

The committed budget contract is inactive, has a total ceiling of zero, permits
zero calls and tokens, and has no reservation. This is a stop condition, not a
placeholder authorization.

A later active budget must be versioned and bind the corpus digest, executed
commit, operator-instruction hash, currency, every provider role and model,
conservative rate basis, call or token ceilings, total ceiling, issue time, short
expiry, and reservation. Activate it only after rights, value, legacy, and
LightRAG capability gates are green.

Before attaching a credential or transmitting any source-derived field, local
preflight must validate the declared credential source, expected public host or
approved loopback proxy, TLS policy, redirect rejection, scope, and rights match.
A bounded network probe may then test only auth and billing readiness without
source content. Do not persist response text, private endpoint values, account
data, or secrets. A lost paid-probe response is indeterminate and must not be
automatically retried.

## LightRAG Stages

LightRAG mutation is unavailable. The read-only audit scanned the deployed
document inventory but found no authoritative payload hashes, normalized
fingerprints, embedded source hashes, or Knowledge Hub references. The advertised
insert contract also lacks a payload-hash and fencing or lease field. It therefore
cannot prove legacy absence or enforce the required stable `file_source` to
immutable payload-hash contract.

When eligible, stages are cumulative:

1. Gate 1 selects exactly one eligible `source_card` using the lowest numeric
   risk rank as the highest-risk sentinel.
2. Gate 2 preserves Gate 1 and adds exactly four new source hashes for five total,
   using deterministic role and size stratification.
3. Gate 3 uses only `ark_lowmod_controlled_ab` members, adds at least three new
   source hashes and two relationship patterns, and treats prior members as
   no-ops.
4. Full apply requires the independent holdout, a fresh rehearsed checkpoint,
   exact expected-count math, and zero unresolved conflicts in the eligible set.

Every mutating batch requires a private owner-only checkpoint, an offline restore
rehearsal, a signed hash-chained write-ahead intent, a service-enforced lease or
fencing token, and stable IDs. A logical ID with a different payload hash is a
conflict, never an update by implication.

The compatibility stage runner additionally binds every stage ledger to the
exact source P0-P8 certification, card manifest, and LightRAG apply plan. A
changed binding blocks the next stage before an insert. Black Label build run IDs
are exclusive, and an already applied or mutating stage ledger is not silently
overwritten by a replay.

There is no automatic fallback for a successful stage created before those
bindings existed. The explicit `migrate-legacy-bindings` command is the only
upgrade path. It requires operator-supplied canonical hashes for both the exact
source certification and its composite consumed bundle; a `legacy_p0p8_v1`
field inside a mutable artifact or the certification hash alone is not
authorization. The composite binding covers the ordered normalized output,
crosswalk, CAG candidates, and referenced text artifacts verified against their
declared SHA-256. The command regenerates the cards and plan canonically, validates
a contiguous successful ledger prefix, and performs only live health, index,
and query-recovery reads. It never calls `insert_texts`, never rewrites the
historical ledger, and writes one hash-bound sidecar only after every check
passes. Run `refresh-certification` immediately after a successful migration;
every later legacy refresh and apply must repeat both exact hashes. Refresh
revalidates and preserves the sidecar anchor before another stage can use the
historical ledger. Apply also reloads the exact source bundle and canonically
regenerates the cards and plan in a contained temporary directory; pointing a
Black Label run at a different authorized source blocks before client creation.

```bash
uv run --project backend python scripts/docling_black_label_package.py \
  migrate-legacy-bindings \
  --source-run logs/post-docling-p0-p8-harness/<verified-source-run> \
  --black-label-run logs/black-label-docling/<verified-black-label-run> \
  --legacy-source-certification-hash <verified-canonical-source-hash> \
  --legacy-source-bundle-hash <verified-composite-source-bundle-hash>

uv run --project backend python scripts/docling_black_label_package.py \
  refresh-certification \
  --source-run logs/post-docling-p0-p8-harness/<verified-source-run> \
  --black-label-run logs/black-label-docling/<verified-black-label-run> \
  --legacy-source-certification-hash <verified-canonical-source-hash> \
  --legacy-source-bundle-hash <verified-composite-source-bundle-hash>
```

Missing or mismatched schema/provenance, artifact drift, ledger drift, failed
live recovery, a busy pipeline, an absent or mismatched explicit legacy hash
pair,
or a pre-existing malformed sidecar blocks the migration without an insert.
The initial blocked migration result exposes the canonical source binding for
operator verification but grants no authority and writes no sidecar. Historical
certifications without a provenance field can be attested only through this
exact hash; their files are never edited. The current Seedance rollout is
P0-blocked, so this command is documented for compatibility and must not be run
for the current corpus.

The terminal LightRAG result may be `candidate_certified` only after full-corpus
certification and graph freeze. The current result is not a candidate and P1 is
`no_go`.

Both generated certification files expose `governed_p1_authorization`. A
governed source can reach the legacy Black Label stage engine only when
`authorized`, `separately_reviewed`, and `controller_ready` are all `true` in
addition to a green P0 result. The current P0 adapter hard-codes all three to
`false`. The legacy certification and bundle hash flags cannot override
governed authorization or reclassify the current corpus; they apply only to an
exact legacy or unmarked historical P0-P8 source bundle.

All staged apply commands also require a client adapter that advertises and
implements service-enforced single-use fencing bound to the Black Label
certification, stage, input bindings, batch, ordered payload hashes, file
sources, expiry, and nonce. A local exclusive claim is additional same-host
protection only. The currently audited LightRAG API has no such remote contract,
so the production client is blocked before insertion even when all local
artifacts are green.

## Knowledge Hub Promotion

Knowledge Hub promotion has a separate ledger, authorization, and state machine.
It does not share the LightRAG mutation authorization. A certified LightRAG
candidate may exist while Knowledge Hub remains `not_started` or `no_go`.

Do not open the Knowledge Hub execute gate unless a read-only audit proves:

- typed import dry-run and exact request hashing;
- atomic import or atomic manifest swap;
- server-enforced single-use authorization;
- a Knowledge Hub-owned lease/TTL or independent orphan-gate watchdog;
- crash-safe gate closure;
- restart request and status operations;
- post-restart read-only health;
- historical ID and unordered-edge preservation.

The read-only Knowledge Hub audit found import routes, but it could not prove
atomic candidate commit and found no advertised single-use authorization,
watchdog or lease TTL, typed gate-close, or restart control. Those missing
capabilities are a pre-open no-go. A successful import is only
`imported_unverified` until the gate is closed, restart health is green, parity is
reconciled, and native regressions pass. Never repair promotion by direct
Postgres, Qdrant, Redis, Chroma, or GraphML mutation.

## Recovery

On timeout, lost response, partial result, digest drift, or process interruption:

1. stop all advancement and mark the phase `indeterminate`;
2. preserve append-only intent and result events;
3. wait for authoritative idle or settlement state;
4. reconcile stable identity, immutable payload hashes, pipeline state, counts,
   and query recovery;
5. resume idempotently only when all evidence agrees.

Do not automatically delete inserted material, edit GraphML, repair a datastore,
or restore coordinated storage. Any restoration or destructive recovery requires
a separate explicit decision and a verified checkpoint.

## Required Public Report Evidence

The delivery report must identify, without private values:

- current P0, LightRAG, and Knowledge Hub states;
- corpus and holdout digests;
- source counts by media type, rights class, disposition, and eligibility;
- baseline and candidate metrics as separate records;
- legacy-reconciliation and capability-audit results;
- provider-call and write counts;
- budget status and bounded totals;
- checkpoint and restore-rehearsal status;
- stage and candidate certificate IDs and hashes;
- Knowledge Hub dry-run, preservation, gate-closure, and restart results;
- executed commit, tests, pull request, CI, and snapshot evidence.

Unknown values stay explicit placeholders. Never substitute chat history or a
process-presence claim for machine evidence.

## Current Next Safe Step

Remain read-only. Obtain source-hash-bound rights records for each intended local
use, capture the independent baseline, and implement or independently prove the
missing legacy-identity, immutable-payload, and service-fencing guarantees.
Revalidate the manifest only after those artifacts exist. Until at least one
value-bearing source is locally eligible and the LightRAG contract is proven, P0
stays `blocked_no_mutation` and P1 stays `no_go`.

The current rollback boundary is repository-only because no provider call or
runtime mutation occurred. Reverting the policy and documentation files is
sufficient; no graph, index, database, source, or Knowledge Hub restore is
required.
