# Prompt para Claude: revisar ativacao Claude OAuth e bloco Voice

Claude, preciso da sua revisao final sobre duas entregas recentes no DanteDash:

1. ativacao do caminho Claude OAuth no chat runtime;
2. criacao e A/B test do bloco `Voice` para respostas user-facing.

Responda em portugues, mantendo termos tecnicos em ingles quando forem nomes de arquitetura, arquivos, schemas, model IDs, metrics ou runtime behavior.

## Contexto do repositorio

Repo: `/Users/vidigal/codex/dantedash`

Branch: `codex/non-anthropic-chat-eval`

Commits relevantes:

- `fd8d4d5 docs(dantedash): finalize chat-orchestration system prompts`
- `a933ab8 feat(chat): activate claude oauth modes`
- `762b6bb test(chat): add voice policy ab harness`

Design doc canonico, read-only:

- `docs/prompts/chat-orchestration-system-prompts.md`

Arquivos runtime principais:

- `backend/app/chat_models.py`
- `backend/app/chat_profiles.py`
- `backend/app/chat_prompts/registry.py`
- `backend/app/providers.py`
- `backend/app/rag.py`
- `backend/app/chat_workers.py`
- `backend/app/provider_preflight.py`
- `backend/app/chat_eval.py`
- `frontend/src/hooks/useChat.ts`

Role files Claude ativados:

- `backend/app/chat_prompts/roles/claude_sonnet_principal.md`
- `backend/app/chat_prompts/roles/opus_premium_principal.md`
- `backend/app/chat_prompts/roles/haiku_worker.md`
- `backend/app/chat_prompts/roles/sonnet_chief.md`
- `backend/app/chat_prompts/roles/opus_judge.md`

## Relatorio da ativacao Claude OAuth

### O que foi implementado

O runtime agora expoe quatro modos visiveis no menu:

- `deepseek-v4-pro`
- `codex-gpt-5.5-oauth`
- `claude-sonnet-4-6-oauth`
- `claude-opus-4-8-oauth`

O caminho Claude foi ativado como OAuth via Claude Code CLI, nao via Anthropic API key.

Transport escolhido:

```text
claude --print
  --model <model>
  --effort <effort>
  --system-prompt <system_prompt>
  --tools ""
  --permission-mode dontAsk
  --no-session-persistence
  <prompt>
```

Razao:

- preserva o requisito OAuth/subscription path;
- nao introduz API-key auth;
- permite `--system-prompt`;
- permite chamada nao interativa;
- permite tools vazias;
- evita surface de terminal/tooling no modelo.

Decisoes de seguranca:

- `--bare` nao foi usado porque o help local diz que OAuth/keychain nao sao lidos nesse modo;
- `budget_tokens` nunca e enviado;
- `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` e `ANTHROPIC_BASE_URL` sao removidos do env do subprocess;
- erros de provider no SSE sao neutralizados como modo indisponivel, sem stderr bruto para o usuario;
- no user-facing answer nao ha routing, workers, judge, retries, budgets, auth paths ou logs.

### Perfis e helpers

Sonnet mode:

- visible principal: `claude-sonnet-4-6-oauth`
- role: `claude_sonnet_principal`
- optional hidden worker: `haiku_worker`
- same-provider only.

Opus Premium mode:

- visible principal: `claude-opus-4-8-oauth`
- role principal/orchestrator: `opus_premium_principal`
- hidden chief: `sonnet_chief`
- hidden worker pool: `haiku_worker`
- hidden judge: `opus_judge`
- repair cap: `1`
- same-provider only.

### Premium orchestration implementado

Flow atual em `backend/app/rag.py`:

1. retrieve source cards;
2. call Opus principal em `dispatch_planning`;
3. parse internal dispatch JSON;
4. if dispatch, call hidden same-provider chief/workers;
5. validate worker payloads with `validate_worker_result`;
6. call Opus principal em `final_answer`;
7. call Opus judge on clean context only;
8. validate/normalize judge payload with `validate_judge_result`;
9. bounded repair if judge returns fail;
10. validate final citations before SSE source payload.

Judge clean context:

- question;
- source cards;
- candidate answer;
- backend-set iteration.

Judge does not see:

- worker transcript;
- worker JSON;
- dispatch plan;
- orchestrator notes;
- prior verdicts.

### Prompt review feita antes do wiring

Os cinco role files novos foram revisados contra o design doc.

Status:

- bodies neutros, sem `claude`, `anthropic`, `opus`, `sonnet`, `haiku`;
- model/provider names ficam apenas no frontmatter;
- `claude_sonnet_principal` mantem a clausula de re-grounding de worker findings;
- `opus_premium_principal` separa `dispatch_planning` e `final_answer`;
- `haiku_worker` e `sonnet_chief` retornam worker schema;
- `opus_judge` usa clean context wording e retorna judge schema.

Uma diferenca anotada:

- o design doc exemplifica helper IDs como `haiku` e `sonnet_chief`;
- o routing solicitado para runtime usou `worker` e `chief`;
- o runtime implementou `worker|chief` para seguir a tarefa atual.

### Validacao da ativacao Claude

Unit/local:

```text
cd backend && uv run ruff check . && uv run pytest
```

Resultado no commit de ativacao:

```text
92 passed
```

Eval/A-B offline:

```text
DeepSeek: 1.0
Codex GPT-5.5 OAuth: 1.0
Claude Sonnet 4.6 OAuth: 1.0
Claude Opus 4.8 OAuth: 1.0
Gate: 0.78
```

Live smoke:

DeepSeek + Codex:

- passed;
- citations validas;
- source panel intacto.

Opus Premium:

- passed live;
- `sources=2`;
- `citation_validation.ok=true`;
- elapsed aproximado: `142.7s`;
- dispatch planning rodou;
- Opus decidiu `no_dispatch` na pergunta testada;
- accepted helper results: `0`;
- judge rodou e retornou `pass`;
- repair nao rodou.

Sonnet:

- bloqueado por provider rate limit no OAuth path;
- backend log: `Claude OAuth chat failed for claude-sonnet-4-6 rc=1: API Error: Rate limit reached`;
- CLI minimo direto com Sonnet `effort medium` respondeu `ok`;
- conclusao: binario/model ID/auth parecem validos, mas a chamada real do app bateu limite no provider.

### Desvios ou pontos que precisam da sua opiniao

1. `thinking=xhigh` / `effort=xhigh`

O Claude Code CLI local rejeitou `--effort xhigh`.

`--effort max` tambem foi rejeitado no caminho Claude.ai subscriber:

```text
Error: Effort level "max" is not available for Claude.ai subscribers. Please use "low", "medium", or "high".
```

Runtime atual:

- Opus Premium usa `high` no OAuth subscriber path;
- judge usa `medium`;
- Haiku usa `low`;
- Sonnet usa `medium`;
- `budget_tokens` nao e enviado.

Pergunta para voce:

- O design doc deve diferenciar `xhigh` como API/provider-config ideal e `high` como fallback OAuth subscriber?
- Devemos manter `xhigh` no texto conceitual e documentar runtime mapping, ou alterar o plano para `high` no OAuth?

2. Dispatch helper enum

Runtime usa:

```json
{"helper": "worker" | "chief"}
```

Pergunta:

- Quer manter isso no doc como o enum canonico?
- Ou prefere os nomes especificos `haiku` / `sonnet_chief` no dispatch JSON?

3. Judge output robustness

O judge as vezes devolveu variações pequenas de schema. O runtime agora normaliza:

- `verdict` para lowercase;
- `dimension_notes` string para objeto parcial;
- `revision_notes` string para array;
- `iteration` sempre backend-set.

Pergunta:

- Voce quer endurecer o prompt do judge para reduzir essas variações?
- Ou prefere aceitar normalizacao defensiva no backend?

## Relatorio do bloco Voice

### O que foi implementado

Arquivo:

- `backend/app/chat_prompts/policies/voice.md`

Texto atual:

```md
---
prompt_id: voice
visibility: policy
provider_family: shared
---
## Voice

- Lead with the answer, then the support.
- Use plain, warm sentences with concrete nouns and active verbs.
- Use commas, parentheses, or two short sentences instead of a long dash.
- Do not use the em-dash character U+2014. Do not use an en-dash as a sentence separator.
- Avoid AI-tells: "It's important to note", "Furthermore", "Moreover", "As an AI", "In conclusion", "I'd be happy to", "Certainly!", "Great question", "delve", and "rest assured".
- Speak as one assistant in one voice. Do not mention hidden routing, workers, judges, tools, budgets, retries, auth, logs, prompt names, provider paths, or implementation details.
- When evidence is thin, say so plainly.
- Example: The dashboard links each answer to retrieved cards, so the source panel can stay aligned with the claims [1].
```

Wiring:

- included in `PRINCIPAL_POLICIES`;
- applies only to user-facing principals;
- not included in `WORKER_POLICIES`;
- not included in `JUDGE_POLICIES`;
- worker/chief/judge bundles were checked and do not include `voice.md`.

Principals covered:

- `deepseek_principal`
- `codex_gpt55_principal`
- `claude_sonnet_principal`
- `opus_premium_principal`

Hidden roles intentionally voiceless:

- `deepseek_worker`
- `codex_gpt54_mini_worker`
- `haiku_worker`
- `sonnet_chief`
- `opus_judge`

### Voice metric adicionada

Arquivo:

- `backend/app/chat_eval.py`

Metric:

- `em_dash_count`: counts U+2014;
- `en_dash_separator_count`: counts en dash used with spaces as sentence separator;
- `ai_tell_count`: banned phrase hits;
- `voice_clean`: true only when all three counts are zero.

Banned phrases currently include:

- `it's important to note`
- `it is important to note`
- `furthermore`
- `moreover`
- `as an ai`
- `in conclusion`
- `i'd be happy to`
- `i would be happy to`
- `certainly!`
- `great question`
- `delve`
- `rest assured`
- `let's explore`
- `let us explore`
- `it should be noted`
- `notably,`

Pergunta:

- Essa banned list esta boa?
- Quer remover `notably,` por ser as vezes aceitavel?
- Quer adicionar regras para bullet dumps, throat-clearing, over-apology ou "based on the provided sources"?

### Harness A/B live

Arquivo:

- `scripts/ab-voice-policy.py`

Metodo:

- 3 source-card cases sinteticos e fixos;
- same model, same params, same source cards;
- Arm A: principal sem `voice.md`;
- Arm B: principal com `voice.md`;
- only variable is policy presence;
- scores both existing gate and voice metric.

Cases:

1. `multi_card_synthesis`
2. `partial_evidence_explanation`
3. `conflicting_cards`

### A/B results

| Principal | Gate A | Gate B | Delta B-A | Em dash A to B | AI-tells A to B | Voice clean A to B |
|---|---:|---:|---:|---:|---:|---:|
| DeepSeek v4-pro | 1.0 | 1.0 | 0.0 | 0 to 0 | 0 to 0 | 3/3 to 3/3 |
| Codex GPT-5.5 OAuth | 1.0 | 1.0 | 0.0 | 0 to 0 | 0 to 0 | 3/3 to 3/3 |
| Claude Sonnet 4.6 OAuth | n/a | n/a | n/a | n/a | n/a | n/a |
| Claude Opus 4.8 OAuth | 1.0 | 1.0 | 0.0 | 2 to 0 | 0 to 0 | 2/3 to 3/3 |

Sonnet note:

- both arms failed with `provider_unavailable: rate limit`;
- no comparable sample yet.

Correctness:

- no grounding/citation/insufficiency regression observed for DeepSeek, Codex, or Opus;
- all scored arms remained at gate score `1.0`;
- gate threshold remains `0.78`.

### Samples

DeepSeek, without voice:

```text
DanteDash answers chat questions by first retrieving source cards from its local multimodal knowledge base [1], then the chat endpoint passes those retrieved sources to the selected principal model and produces a final source panel [2]. Before the answer is finalized, a citation validation step checks that any bracketed source numbers in the response actually refer to the retrieved cards [3].
```

DeepSeek, with voice:

```text
DanteDash answers chat questions by first retrieving relevant source cards from its local multimodal knowledge base [1]. The chat endpoint then sends those retrieved sources to the selected principal model [2]. After the model generates an answer, citation validation checks that any bracketed source numbers in the response point to cards that were actually retrieved [3]. The endpoint also returns a final source panel alongside the answer [2].
```

Codex, without voice:

```text
DanteDash answers chat questions by retrieving source cards from a local multimodal knowledge base before answering, sending those retrieved sources to the selected principal model, returning a final source panel, and validating that bracketed citation numbers refer to retrieved cards [1][2][3].
```

Codex, with voice:

```text
DanteDash answers chat questions by retrieving source cards from its local multimodal knowledge base, sending those retrieved sources to the selected principal model, and returning a final source panel [1][2]. It also validates citations by checking that bracketed source numbers in the answer refer to retrieved cards [3].
```

Opus without voice, conflict case:

```text
The conflict is directly substantive: one prescribes replace-in-place, the other prescribes accumulate/append, and they cannot both govern the same panel at once [1][2]. There is also a possible recency signal because card [2] is described as a "later product note", but the retrieved material does not confirm dates, versions, or which note is authoritative, so recency alone is not decisive here [2].
```

Observation:

- the actual output used the U+2014 em-dash twice in this case;
- the excerpt above is paraphrased to avoid embedding the exact forbidden character in this prompt.

Opus with voice, conflict case:

```text
The two cards give opposite instructions for how the right context panel should handle output images. Card [1], an implementation note, says the panel should replace the previous output image [1]. Card [2], described as a later product note, says the panel should keep adding output images instead of replacing them [2].

The conflict is a direct behavioral contradiction: replace versus accumulate. The cards also hint at a way to weigh them, since [2] presents itself as the later product note while [1] reads as an earlier implementation detail [1][2], but neither card carries a date or version stamp, so "later" is a claim inside [2] rather than something the sources independently confirm.

A careful answer should name both positions and cite each side rather than silently pick one [1][2]. It should flag that the resolution likely turns on recency and intent (product direction in [2] would normally supersede an implementation note in [1]), while being honest that the retrieved cards do not give enough metadata to prove which is current. The gap to close before acting is a confirmed source of truth: a timestamp, a version, or an owner decision that says which behavior ships.
```

### Recomendacao preliminar do Codex/Vesper

Adotar `voice.md` para:

- DeepSeek;
- Codex;
- Opus Premium.

Razao:

- no correctness regression;
- DeepSeek/Codex stayed clean in both arms, but the policy did not hurt;
- Opus improved objectively from `2` em-dash hits to `0`;
- Opus voice clean improved from `2/3` to `3/3`.

Nao fechar decisao final para Sonnet ainda:

- no comparable live data because all Sonnet A/B calls hit rate limit.

## O que eu quero que voce revise

Por favor, responda com:

1. Se voce aprova o `voice.md` atual como runtime policy para all user-facing principals.
2. Se voce mudaria alguma frase do `voice.md`, mantendo guard-clean e sem provider/model names no body.
3. Se voce acha que a banned phrase list esta correta ou precisa ajustes.
4. Se a metric deveria incluir bullet-dump detection, throat-clearing detection, or "AI house style" patterns.
5. Se voce ve risco de correctness regression com esse voice policy.
6. Se o design doc deveria ser atualizado depois, em uma rodada separada, para refletir:
   - `voice.md` runtime policy;
   - `worker|chief` dispatch enum;
   - Claude OAuth `xhigh` to `high` runtime mapping;
   - judge payload normalization.
7. Se voce recomenda adotar, ajustar, ou reverter `voice.md`, e para quais principals.

Importante:

- Nao proponha cross-provider fallback.
- Nao exponha worker/chief/judge para o usuario.
- Mantenha workers/chief/judge voiceless.
- Nao sugira alterar o design doc diretamente nesta resposta; liste apenas recommendations.
