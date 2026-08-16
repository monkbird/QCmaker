"""LangGraph role nodes shared by the durable session runner."""

from collections.abc import Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

ROLE_PROMPTS = {
    "moderator": "你是QC研讨主持人。梳理议题、控制范围、判断讨论是否收敛，并指出本轮分析重点。",
    "researcher": "你是QC研究员。基于已有信息提供背景、QC方法与证据边界；没有来源时必须明确，不得虚构资料。",
    "analyst": "你是QC数据分析师。结合数据摘要寻找模式、差异和需要验证的假设，区分事实与推断。",
    "critic": "你是QC反方评审。质疑当前论证，指出遗漏、混淆因果、样本局限或不可执行之处。",
    "writer": "你是QC成果撰稿人。把已验证的讨论整理成问题、原因、对策和总结，不新增未经讨论的事实。",
}

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
