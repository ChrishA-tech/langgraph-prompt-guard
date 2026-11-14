from typing import TypedDict, Optional, Callable, Dict, Any
from .schemas import GuardrailAssessment, ExtractedEntitySchema, WorkflowResponse
from .guardrails import evaluate_prompt_safety
from .extractor import extract_schema_constrained_json
from .exceptions import SchemaExtractionError

try:
    from langgraph.graph import StateGraph, END
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    END = "__END__"


class AgentWorkflowState(TypedDict):
    user_id: str
    raw_prompt: str
    strict_mode: bool
    guardrail_result: Optional[GuardrailAssessment]
    extracted_result: Optional[ExtractedEntitySchema]
    status: str
    error_detail: Optional[str]


class _CompiledFallbackStateGraph:
    """Deterministic StateGraph engine matching LangGraph's compiled graph interface when langgraph is not installed."""
    def __init__(self, nodes, entry_point, conditional_edges, edges):
        self.nodes = nodes
        self.entry_point = entry_point
        self.conditional_edges = conditional_edges
        self.edges = edges

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        current_state = dict(state)
        current_node = self.entry_point
        while current_node != END:
            node_fn = self.nodes[current_node]
            updates = node_fn(current_state)
            if updates:
                current_state.update(updates)
            if current_node in self.conditional_edges:
                router_fn, mapping = self.conditional_edges[current_node]
                route_key = router_fn(current_state)
                current_node = mapping[route_key]
            else:
                current_node = self.edges.get(current_node, END)
        return current_state


def build_langgraph_workflow(llm_callable: Optional[Callable[[str], str]] = None):
    """
    Builds and compiles the multi-step LangGraph state machine:
    [input_guardrail_node] --(safe)--> [llm_extraction_node] --> END
                           --(unsafe)-> [rejection_node]      --> END
    """

    def input_guardrail_node(state: AgentWorkflowState) -> dict:
        assessment = evaluate_prompt_safety(
            prompt=state["raw_prompt"],
            strict_mode=state.get("strict_mode", True),
        )
        return {"guardrail_result": assessment}

    def route_after_guardrail(state: AgentWorkflowState) -> str:
        assessment = state.get("guardrail_result")
        if assessment and assessment.is_safe:
            return "llm_extraction_node"
        return "rejection_node"

    def llm_extraction_node(state: AgentWorkflowState) -> dict:
        assessment = state["guardrail_result"]
        try:
            extracted = extract_schema_constrained_json(
                sanitized_prompt=assessment.sanitized_prompt,
                llm_callable=llm_callable,
            )
            return {
                "extracted_result": extracted,
                "status": "success",
                "error_detail": None,
            }
        except SchemaExtractionError as exc:
            return {
                "extracted_result": None,
                "status": "error",
                "error_detail": exc.message,
            }

    def rejection_node(state: AgentWorkflowState) -> dict:
        assessment = state["guardrail_result"]
        return {
            "extracted_result": None,
            "status": "blocked",
            "error_detail": assessment.reason if assessment else "Blocked by safety guardrail.",
        }

    if HAS_LANGGRAPH:
        graph = StateGraph(AgentWorkflowState)
        graph.add_node("input_guardrail_node", input_guardrail_node)
        graph.add_node("llm_extraction_node", llm_extraction_node)
        graph.add_node("rejection_node", rejection_node)

        graph.set_entry_point("input_guardrail_node")
        graph.add_conditional_edges(
            "input_guardrail_node",
            route_after_guardrail,
            {
                "llm_extraction_node": "llm_extraction_node",
                "rejection_node": "rejection_node",
            },
        )
        graph.add_edge("llm_extraction_node", END)
        graph.add_edge("rejection_node", END)
        return graph.compile()

    return _CompiledFallbackStateGraph(
        nodes={
            "input_guardrail_node": input_guardrail_node,
            "llm_extraction_node": llm_extraction_node,
            "rejection_node": rejection_node,
        },
        entry_point="input_guardrail_node",
        conditional_edges={
            "input_guardrail_node": (
                route_after_guardrail,
                {
                    "llm_extraction_node": "llm_extraction_node",
                    "rejection_node": "rejection_node",
                },
            )
        },
        edges={
            "llm_extraction_node": END,
            "rejection_node": END,
        },
    )


def run_protected_extraction_workflow(
    user_id: str,
    prompt: str,
    strict_mode: bool = True,
    llm_callable: Optional[Callable[[str], str]] = None,
) -> WorkflowResponse:
    """Executes the compiled LangGraph workflow and returns a validated WorkflowResponse."""
    app = build_langgraph_workflow(llm_callable=llm_callable)
    final_state = app.invoke(
        {
            "user_id": user_id,
            "raw_prompt": prompt,
            "strict_mode": strict_mode,
            "guardrail_result": None,
            "extracted_result": None,
            "status": "pending",
            "error_detail": None,
        }
    )
    return WorkflowResponse(
        status=final_state["status"],
        guardrail=final_state["guardrail_result"],
        extracted_data=final_state["extracted_result"],
        error_detail=final_state["error_detail"],
    )
