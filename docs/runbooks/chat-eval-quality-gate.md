# DanteDash Chat Eval Quality Gate

This runbook covers the active non-Anthropic chat modes only:

- `deepseek - deepseek-v4-pro`
- `openai/codex - gpt-5.5 OAuth`

Anthropic, Claude, Opus, Sonnet, and Haiku modes are intentionally outside this runtime round.

## Gate

Each implemented visible mode must score at least `0.78` on the latest eval pass. Hidden workers are also gated at `0.78` when runtime-enabled.

The deterministic score combines grounding, citation validity, insufficiency calibration, source-panel consistency, provider isolation, worker-contract validity, and latency/reliability.

## Offline Eval

```bash
python scripts/eval-chat-models.py
python scripts/eval-chat-models.py --json
```

The offline fixture eval is deterministic and CI-safe. It does not call live providers or mutate the knowledge base.

## Offline A/B

```bash
python scripts/ab-chat-models.py
python scripts/ab-chat-models.py --json
```

The A/B harness compares the two active visible modes over the same fixture set and reports per-case winners or ties. It still requires both modes to pass the `0.78` gate.

## Live Smoke

Run the normal read-only dashboard smoke after backend/frontend changes:

```bash
scripts/smoke-dante-dashboard.sh
```

Run the live chat smoke against the active backend after restarting it onto the current branch:

```bash
python scripts/live-smoke-chat-models.py
python scripts/live-smoke-chat-models.py --json
```

Provider live checks must not print secrets, OAuth files, account identifiers, or raw provider logs.

If a provider returns `provider_unavailable`, the mode has not passed the live quality/reliability gate. For example, a DeepSeek `402 Insufficient Balance` proves routing works up to the provider but blocks goal completion until account balance is restored.

## Latest Gate Evidence

Last checked after the DeepSeek account balance was restored:

- Offline eval: both active modes scored `1.0`, above the `0.78` gate.
- Offline A/B: both active modes tied at `1.0` on the deterministic fixture set.
- Runtime was restarted through LaunchAgent `com.vidigal.obsidian-dante-multimodal-rag` so `127.0.0.1:8035` loaded the current code.
- Live smoke against the active runtime on `127.0.0.1:8035`:
  - `deepseek-v4-pro`: `ok`, one source returned, `citation_validation.ok=true`.
  - `codex-gpt-5.5-oauth`: `ok`, one source returned, `citation_validation.ok=true`.

Do not mark the full chat-model goal complete until `python scripts/live-smoke-chat-models.py --api-base <current-backend>` returns `ok` for every active visible mode without `--allow-provider-unavailable`.
