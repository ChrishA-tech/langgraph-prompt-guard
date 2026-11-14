import json
import re
from typing import Callable, Optional
from pydantic import ValidationError
from .schemas import ExtractedEntitySchema
from .exceptions import SchemaExtractionError


def default_structured_llm_simulator(sanitized_prompt: str) -> str:
    """
    Deterministic schema-aligned LLM extractor for reliable offline execution and testing.
    Can be swapped with any LangChain/OpenAI/vLLM callable returning a JSON string.
    """
    lower = sanitized_prompt.lower()
    if any(k in lower for k in ["cpi", "inflation", "revenue", "rate", "price", "sec", "10-k", "earnings"]):
        intent = "financial_query"
    elif any(k in lower for k in ["summarize", "summary", "overview", "tl;dr"]):
        intent = "document_summary"
    elif any(k in lower for k in ["extract", "parse", "json", "fields"]):
        intent = "data_extraction"
    else:
        intent = "general_inquiry"

    # Extract capitalized entities and numeric percentages/currencies
    capitalized = re.findall(r"\b[A-Z][a-zA-Z0-9&\-]{2,}\b", sanitized_prompt)
    metrics = re.findall(r"\b\d+(?:\.\d+)?(?:%|(?:\s*(?:million|billion|bps|USD|GBP)\b))?", sanitized_prompt)
    entities = list(dict.fromkeys(capitalized[:6]))

    sentiment = "neutral"
    if any(w in lower for w in ["surge", "growth", "profit", "beat", "strong", "improve"]):
        sentiment = "positive"
    elif any(w in lower for w in ["drop", "decline", "loss", "risk", "crisis", "miss"]):
        sentiment = "negative"

    payload = {
        "intent": intent,
        "entities": entities,
        "sentiment": sentiment,
        "confidence": 0.93,
        "structured_payload": {
            "detected_metrics": metrics,
            "token_count": len(sanitized_prompt.split()),
        },
    }
    return json.dumps(payload)


def extract_schema_constrained_json(
    sanitized_prompt: str,
    llm_callable: Optional[Callable[[str], str]] = None,
) -> ExtractedEntitySchema:
    """Executes LLM extraction and enforces strict Pydantic schema compliance."""
    runner = llm_callable or default_structured_llm_simulator
    raw_response = runner(sanitized_prompt)

    try:
        parsed_dict = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise SchemaExtractionError(
            f"LLM output is not valid JSON: {exc}", raw_output=raw_response
        ) from exc

    try:
        return ExtractedEntitySchema.model_validate(parsed_dict)
    except ValidationError as exc:
        raise SchemaExtractionError(
            f"LLM JSON violated target Pydantic schema: {exc}", raw_output=raw_response
        ) from exc
