# Project 1: LLM Prompt Protection & Validation (AI Safety) – LangGraph

## Architecture
- **Input Guardrail Node (`guardrails.py`)**: Screens user inputs against prompt injection (e.g., `ignore previous instructions`, `system prompt`, `DAN`, roleplay overrides, Base64/hex obfuscation, SQL/shell injection patterns) and calculates a composite risk score `[0.0, 1.0]`.
- **LLM Extraction Node (`extractor.py`)**: Processes sanitized, safe prompts and enforces schema-constrained JSON output validated via Pydantic (`ExtractedEntitySchema`). Supports live LLM invocation or deterministic local structured extraction for testing/CI.
- **LangGraph Workflow (`workflow.py`)**: Orchestrates state transitions (`GuardrailState`) with conditional routing: safe inputs proceed to `llm_extraction_node`; flagged inputs route to `rejection_node` with structured audit metadata.
- **FastAPI Backend Service (`api.py`)**: Exposes `POST /api/v1/extract` and `GET /health` with structured error handling, correlation IDs, and HTTP 422/403 safety enforcement.
