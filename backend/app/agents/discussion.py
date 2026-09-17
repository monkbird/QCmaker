"""LangGraph role nodes shared by the durable session runner."""

from collections.abc import Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.services.qc_coaching import QC_CHAIN, ROLE_BOUNDARIES

ROLE_PROMPTS = {role: QC_CHAIN + '\n' + ROLE_BOUNDARIES[role] for role in ('moderator', 'researcher', 'analyst', 'critic', 'writer')}

FALLBACK_ORDER = ("researcher", "analyst", "critic")


class RoleState(TypedDict):
    cursor: int


async def run_role_graph(roles: list[str], runner: Callable[[str], Awaitable[None]]) -> None:
    """Run the selected role nodes; durable state remains outside LangGraph."""
    if not roles: return
    graph = StateGraph(RoleState)
    for index, role in enumerate(roles):
        async def node(state: RoleState, current_role: str = role) -> RoleState:
            await runner(current_role)
            return {"cursor": state["cursor"] + 1}

        graph.add_node(role, node)
        if index == 0: graph.add_edge(START, role)
        graph.add_edge(role, roles[index + 1] if index + 1 < len(roles) else END)
    await graph.compile().ainvoke({"cursor": 0})
