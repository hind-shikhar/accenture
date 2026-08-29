from typing import Dict, Any, TypedDict
from langgraph.graph import StateGraph, END
import uuid

class ReviewState(TypedDict):
    request_id: str
    prompt: str
    response: str
    trust_score: float
    risk_level: str
    status: str # pending, approved, rejected, escalated

def route_based_on_risk(state: ReviewState):
    if state["risk_level"] == "high" or state["trust_score"] < 70:
        return "human_review"
    return "auto_approve"

def auto_approve(state: ReviewState):
    state["status"] = "approved"
    return state

def human_review(state: ReviewState):
    state["status"] = "pending"
    # In a real app, this would pause the graph or notify a queue.
    # For MVP, we will store this state in DB and the API will return a 202 Accepted.
    return state

# Setup LangGraph
workflow = StateGraph(ReviewState)

workflow.add_node("auto_approve", auto_approve)
workflow.add_node("human_review", human_review)

workflow.set_conditional_entry_point(
    route_based_on_risk,
    {
        "auto_approve": "auto_approve",
        "human_review": "human_review"
    }
)

workflow.add_edge("auto_approve", END)
workflow.add_edge("human_review", END)

app_graph = workflow.compile()
