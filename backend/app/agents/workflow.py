"""LangGraph wiring for the Sentry / Analyst / Strategist pipeline."""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.analyst import analyst_node
from app.agents.sentry import sentry_node
from app.agents.state import WorkflowState
from app.agents.strategist import strategist_node


def _route_after_sentry(state: WorkflowState) -> str:
    return "error" if state.get("error") else "analyst"


def build_workflow():
    g = StateGraph(WorkflowState)
    g.add_node("sentry", sentry_node)
    g.add_node("analyst", analyst_node)
    g.add_node("strategist", strategist_node)

    g.set_entry_point("sentry")
    g.add_conditional_edges(
        "sentry",
        _route_after_sentry,
        {"analyst": "analyst", "error": END},
    )
    g.add_edge("analyst", "strategist")
    g.add_edge("strategist", END)

    return g.compile()


_compiled = None


def get_compiled_workflow():
    global _compiled
    if _compiled is None:
        _compiled = build_workflow()
    return _compiled


def run_match_workflow(truck_id: int, *, use_mock_llm: bool = False) -> WorkflowState:
    workflow = get_compiled_workflow()
    initial: WorkflowState = {"truck_id": truck_id, "use_mock_llm": use_mock_llm}
    return workflow.invoke(initial)
