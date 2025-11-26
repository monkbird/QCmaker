from typing import TypedDict, Annotated, List, Union
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from backend.app.core.config import settings
import operator

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    next_agent: str
    iteration_count: int

class DiscussionOrchestrator:
    def __init__(self):
        self.llm = None
        self.graph = self._build_graph()

    def _get_llm(self):
        if not self.llm and settings.OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                base_url=settings.OPENAI_BASE_URL,
                api_key=settings.OPENAI_API_KEY,
                model="gpt-4o",
                temperature=0.7
            )
        return self.llm

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        # Define Nodes
        workflow.add_node("moderator", self.moderator_agent)
        workflow.add_node("researcher", self.researcher_agent)
        workflow.add_node("analyst", self.analyst_agent)
        workflow.add_node("critic", self.critic_agent)
        workflow.add_node("writer", self.writer_agent)

        # Define Edges
        workflow.set_entry_point("moderator")
        
        workflow.add_conditional_edges(
            "moderator",
            lambda state: state["next_agent"],
            {
                "researcher": "researcher",
                "analyst": "analyst",
                "critic": "critic",
                "writer": "writer",
                "FINISH": END
            }
        )
        
        workflow.add_edge("researcher", "moderator")
        workflow.add_edge("analyst", "moderator")
        workflow.add_edge("critic", "moderator")
        workflow.add_edge("writer", "moderator") # Writer sends back to moderator to decide if done

        return workflow.compile()

    async def moderator_agent(self, state: AgentState):
        messages = state["messages"]
        # Simple logic for demo: Round Robin or based on last message
        last_message = messages[-1]
        
        if "TERMINATE" in last_message.content:
            return {"next_agent": "FINISH"}
            
        # Demo logic: 
        # User -> Moderator -> Researcher -> Analyst -> Critic -> Writer -> Finish
        
        # In a real app, use LLM to decide next step
        # prompt = "Based on history, who should speak next?"
        # response = await self.llm.invoke(...)
        
        # Hardcoded flow for prototype
        current_step = len(messages)
        if current_step == 1: # After user input
            return {"next_agent": "researcher", "messages": [AIMessage(content="主持人: 收到课题。首先请研究员搜集相关背景资料。")]}
        elif isinstance(last_message, AIMessage) and "研究员" in last_message.content:
             return {"next_agent": "analyst", "messages": [AIMessage(content="主持人: 资料已收到。请数据分析师进行分析。")]}
        elif isinstance(last_message, AIMessage) and "数据分析师" in last_message.content:
             return {"next_agent": "critic", "messages": [AIMessage(content="主持人: 分析完成。请反方进行批判。")]}
        elif isinstance(last_message, AIMessage) and "反方" in last_message.content:
             return {"next_agent": "writer", "messages": [AIMessage(content="主持人: 讨论充分。请撰稿人总结。")]}
        elif isinstance(last_message, AIMessage) and "撰稿人" in last_message.content:
             return {"next_agent": "FINISH", "messages": [AIMessage(content="主持人: 讨论结束。TERMINATE")]}
        
        return {"next_agent": "FINISH"}

    async def researcher_agent(self, state: AgentState):
        # Simulate research
        return {"messages": [AIMessage(content="研究员: 我查阅了相关国标和行业数据... [模拟数据]")]}

    async def analyst_agent(self, state: AgentState):
        # Simulate analysis
        return {"messages": [AIMessage(content="数据分析师: 根据数据，不良率主要集中在... [模拟分析]")]}

    async def critic_agent(self, state: AgentState):
        # Simulate critique
        return {"messages": [AIMessage(content="反方: 我认为分析还不够深入，是否考虑了环境因素？ [模拟批判]")]}

    async def writer_agent(self, state: AgentState):
        # Simulate writing
        return {"messages": [AIMessage(content="撰稿人: 综合各方意见，形成如下结论... [模拟总结]")]}

discussion_orchestrator = DiscussionOrchestrator()
