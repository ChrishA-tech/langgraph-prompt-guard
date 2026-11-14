# LLM Prompt Protection & Validation: LangGraph Guarded Extraction

A **LangGraph** workflow that screens prompts for injection and jailbreak attempts, sends safe prompts to an LLM
(**Claude**, or a deterministic simulator offline) for **schema-constrained JSON extraction** with a
**self-repair retry**, and checks the LLM output for **PII, secrets and system-prompt leakage** before returning it.
Served through FastAPI with request IDs and a structured audit log.

Input screening has two layers: explainable **rules** first, then a **learned classifier** (TF-IDF n-grams +
logistic regression, trained on deepset/prompt-injections) that catches paraphrased and German attacks the rules miss.

```
input_guardrail ──safe──▶ llm_extraction ──valid──▶ output_guard ──▶ END
      │                       │  ▲  invalid JSON/schema: retry with the validation error
      └──unsafe──▶ rejection  └──┘  (max_attempts), then status=error
```

## Evaluation

<!-- RESULTS:START -->
Run 2026-11-14. A prompt counts as flagged when the guardrail blocks it.

| Dataset | Guardrail | Precision | Recall | F1 | False-positive rate | Accuracy |
|---|---|---|---|---|---|---|
| Dev set (60, in-sample) | v1 (original) | 0.857 | 0.400 | 0.545 | 0.067 | 0.667 |
| Dev set (60, in-sample) | v2 strict | 0.968 | 1.000 | 0.984 | 0.033 | 0.983 |
| Dev set (60, in-sample) | v2 lenient | 0.967 | 0.967 | 0.967 | 0.033 | 0.967 |
| deepset/prompt-injections (662, held-out) | v1 (original) | 1.000 | 0.011 | 0.023 | 0.000 | 0.607 |
| deepset/prompt-injections (662, held-out) | v2 strict | 1.000 | **0.080** | **0.148** | 0.000 | 0.634 |
| deepset/prompt-injections (662, held-out) | v2 lenient | 1.000 | 0.080 | 0.148 | 0.000 | 0.634 |

Held-out (deepset, v2 strict): 21/263 attacks flagged, 0/399 benign prompts wrongly flagged, 0.059 ms per prompt. Rule-based screening misses many paraphrased and non-English injections; see results/eval.md for examples.
<!-- RESULTS:END -->

- **Dev set** (60 hand-written prompts): used while writing the v2 rules, so in-sample for the rules; the
  classifier never saw it, so for the classifier it is an out-of-distribution check.
- **deepset/prompt-injections** (English and German): never used to build the rules. The classifier is trained
  on its **train split only** (regularisation and decision threshold chosen by 5-fold cross-validation inside the
  train split) and scored once on the **test split**, the headline comparison. The test split is small, so
  recall is shown with a 95% Wilson interval.
- Rules are fast and explainable but miss paraphrased attacks on their own; the classifier closes much of that
  gap; the output guard and schema validation remain the last line of defence.

## Components

| Part | File | |
|---|---|---|
| Input guardrail v2 | `promptguard/guardrails.py` | Unicode NFKC + zero-width/homoglyph normalisation, leetspeak and spaced-letter views, Base64/hex payload decoding and re-scan, 10 weighted rule families (override, multilingual override, new instructions, prompt exfiltration, jailbreak persona, role-play override, delimiter escaping, code/SQL injection, markdown data exfiltration, harmful misuse), threshold scoring (strict 0.50 / lenient 0.75) |
| Learned classifier | `promptguard/classifier.py` | Char (2-5) + word (1-2) TF-IDF on normalised text, class-balanced logistic regression; C and threshold by CV on training data; saved to `models/` with a model card (`.json`); `hybrid_assess()` = rules, then classifier (rule `ML_CLASSIFIER`) |
| Original guardrail | `promptguard/guardrails_v1.py` | Unchanged v1 rules, kept for comparison |
| LLM extraction | `promptguard/extractor.py` | Pydantic-validated JSON; `make_claude_extractor()` (system prompt treats user text as data, canary token) or offline simulator |
| Workflow | `promptguard/workflow.py` | LangGraph `StateGraph` with conditional routing and self-repair loop; optional `classifier=` for rules + classifier screening; built-in fallback runner when `langgraph` is absent |
| Output guardrail | `promptguard/output_guard.py` | Redacts e-mails, phone numbers, Luhn-valid card numbers, UK NI numbers, IBANs, API keys, private keys; withholds output containing the canary |
| API | `promptguard/api.py` | `POST /api/v1/extract` (200 / 403 blocked / 422 error), `X-Request-ID`; audit log stores a SHA-256 of the prompt, never the raw text |
| Evaluation | `promptguard/evaluate.py` | Trains the classifier on deepset train, then v1 / v2 / classifier / hybrid on the deepset test split and the dev set: precision, recall (95% CI), F1, false-positive rate, latency, error examples |

## Run

```bash
pip install -r requirements.txt
python -m promptguard.evaluate          # downloads deepset/prompt-injections, trains + saves models/, scores all guards
python -m pytest -q
uvicorn promptguard.api:app --reload    # simulator; uses models/ classifier if present (PROMPTGUARD_CLASSIFIER=off to disable)
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
- **Held-out evaluation showed the rules alone catch few real attacks** (21 of 263 on deepset), so a learned
  classifier was added and evaluated on a train/test split it was not tuned on.

This is the team-project guardrail service (input-guardrail + extraction nodes). A separate single-author
guardrail pipeline with LangGraph is at [llm-prompt-guard](https://github.com/ChrishA-tech/llm-prompt-guard).
