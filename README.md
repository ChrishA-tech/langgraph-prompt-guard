# LLM Prompt Protection & Validation: LangGraph Guarded Extraction

A **LangGraph** workflow that screens prompts for injection and jailbreak attempts, sends safe prompts to an LLM
(**Claude**, or a deterministic simulator offline) for **schema-constrained JSON extraction** with a
**self-repair retry**, and checks the LLM output for **PII, secrets and system-prompt leakage** before returning it.
Served through FastAPI with request IDs and a structured audit log.

```
input_guardrail ──safe──▶ llm_extraction ──valid──▶ output_guard ──▶ END
      │                       │  ▲  invalid JSON/schema: retry with the validation error
      └──unsafe──▶ rejection  └──┘  (max_attempts), then status=error
```

## Evaluation

<!-- RESULTS:START -->
_Not run yet: `python -m promptguard.evaluate` downloads the public test set and fills in this section._
<!-- RESULTS:END -->

The **dev set** (60 hand-written prompts) was used while writing the v2 rules, so its scores are in-sample.
The **deepset/prompt-injections** dataset (662 prompts, English and German) was not used to build the rules and
is the held-out estimate. Rule-based screening is fast and explainable but misses paraphrased attacks; the output
guard and schema validation are the second line of defence.

## Components

| Part | File | |
|---|---|---|
| Input guardrail v2 | `promptguard/guardrails.py` | Unicode NFKC + zero-width/homoglyph normalisation, leetspeak and spaced-letter views, Base64/hex payload decoding and re-scan, 10 weighted rule families (override, multilingual override, new instructions, prompt exfiltration, jailbreak persona, role-play override, delimiter escaping, code/SQL injection, markdown data exfiltration, harmful misuse), threshold scoring (strict 0.50 / lenient 0.75) |
| Original guardrail | `promptguard/guardrails_v1.py` | Unchanged v1 rules, kept for comparison |
| LLM extraction | `promptguard/extractor.py` | Pydantic-validated JSON; `make_claude_extractor()` (system prompt treats user text as data, canary token) or offline simulator |
| Workflow | `promptguard/workflow.py` | LangGraph `StateGraph` with conditional routing and self-repair loop; built-in fallback runner when `langgraph` is absent |
| Output guardrail | `promptguard/output_guard.py` | Redacts e-mails, phone numbers, Luhn-valid card numbers, UK NI numbers, IBANs, API keys, private keys; withholds output containing the canary |
| API | `promptguard/api.py` | `POST /api/v1/extract` (200 / 403 blocked / 422 error), `X-Request-ID`; audit log stores a SHA-256 of the prompt, never the raw text |
| Evaluation | `promptguard/evaluate.py` | v1 vs v2 on dev and deepset sets: precision, recall, F1, false-positive rate, latency, error examples |

## Run

```bash
pip install -r requirements.txt
python -m promptguard.evaluate          # downloads deepset/prompt-injections (cached in data/)
python -m pytest -q
uvicorn promptguard.api:app --reload    # simulator
PROMPTGUARD_LLM=claude ANTHROPIC_API_KEY=... uvicorn promptguard.api:app   # Claude
```

## Review notes (Nov 2026)

- **Bug fixed:** percentages lost their `%` sign in extraction (a trailing `\b` after `%` never matches); one of
  the original tests was failing because of it.
- **`strict_mode` had no effect:** v1 blocked any prompt that matched a rule, whatever the mode; v2 applies the
  documented thresholds.
- **Base64 heuristic produced false positives** (any 48+ character token was blocked); v2 decodes payloads and
  blocks only if the decoded text is an attack.
- **README claims without code:** hex obfuscation and role-play overrides were listed but not implemented; both
  are implemented now. Correlation IDs were claimed but missing; the API now returns them and logs every request.
- **Added:** output guardrail, self-repair loop, Claude extractor, and a held-out evaluation.

This is the team-project guardrail service (input-guardrail + extraction nodes). A separate single-author
guardrail pipeline with LangGraph is at [llm-prompt-guard](https://github.com/ChrishA-tech/llm-prompt-guard).
