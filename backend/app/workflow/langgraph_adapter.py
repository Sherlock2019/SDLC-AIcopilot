"""Optional LangGraph view of the same workflow.

The native engine (engine.py) is the default because it has no dependencies and persists state
in the lab's own database. This module compiles the identical step list into a LangGraph
StateGraph, with `interrupt_before` on every human step, for teams that standardise on LangGraph.

    pip install -r requirements-langgraph.txt
"""
from __future__ import annotations

from typing import Callable, TypedDict

from .steps import STEPS


class LabState(TypedDict, total=False):
    run_id: int
    state: str
    last_step: str
    blocked: str


def human_steps() -> list[str]:
    return [step.key for step in STEPS if step.kind in ("approval", "human_action")]


def build_graph(execute: Callable[[str, LabState], dict] | None = None):
    """Return a compiled LangGraph graph. `execute(step_key, state)` performs one step and returns
    a partial state update; by default each node only records the transition."""
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        raise RuntimeError("LangGraph is optional. Install it with: pip install -r requirements-langgraph.txt") from None

    def make_node(step):
        def node(state: LabState) -> dict:
            update = execute(step.key, state) if execute else {}
            return {"state": step.state_done, "last_step": step.key, **(update or {})}
        return node

    graph = StateGraph(LabState)
    for step in STEPS:
        graph.add_node(step.key, make_node(step))
    graph.add_edge(START, STEPS[0].key)
    for current, following in zip(STEPS, STEPS[1:]):
        graph.add_edge(current.key, following.key)
    graph.add_edge(STEPS[-1].key, END)
    return graph.compile(checkpointer=MemorySaver(), interrupt_before=human_steps())
