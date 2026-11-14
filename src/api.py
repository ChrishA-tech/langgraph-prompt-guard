from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from .schemas import PromptInputRequest, WorkflowResponse
from .workflow import run_protected_extraction_workflow

app = FastAPI(
    title="AI Safety Prompt Guard & LangGraph Extraction API",
    version="1.0.0",
    description="Multi-step LangGraph workflow with input-guardrail prompt injection protection and schema-constrained JSON extraction.",
)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "langgraph-prompt-guard"}


@app.post("/api/v1/extract", response_model=WorkflowResponse)
def extract_endpoint(payload: PromptInputRequest):
    result = run_protected_extraction_workflow(
        user_id=payload.user_id,
        prompt=payload.prompt,
        strict_mode=payload.strict_mode,
    )
    if result.status == "blocked":
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=result.model_dump(),
        )
    if result.status == "error":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=result.model_dump(),
        )
    return result
