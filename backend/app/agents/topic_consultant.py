from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from backend.app.core.config import settings
import os
from typing import List

class TopicConsultant:
    def __init__(self):
        self.llm = None # Initialize llm to None
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的 QC 小组活动顾问。你的任务是帮助用户确定 QC 课题。
            遵循 T/CAQ 10201-2020 标准。
            
            你的工作流程：
            1. 分析用户的初步想法。
            2. 判别课题类型（问题解决型 vs 创新型）。如果不清楚，请向用户提问。
            3. 生成 3-5 个规范的课题名称。
               规范格式：XX（对象）+XX（问题）+XX（结果），例如“降低XX车间XX机器的故障率”。
               避免口号式标题。
            
            当前状态：
            {history}
            """),
            ("user", "{input}")
        ])
        # The chain will be initialized in chat method once llm is available
        self.chain = None 

    def _init_llm(self):
        # Simple logic to switch between OpenAI and Local
        if settings.USE_LOCAL_LLM:
            self.llm = ChatOpenAI(
                base_url=settings.LOCAL_LLM_URL,
                api_key="ollama", # Ollama doesn't need a key
                model="llama3", # Or whatever is configured
                temperature=0.7
            )
        elif settings.OPENAI_API_KEY: # Only initialize OpenAI if API key is present
            self.llm = ChatOpenAI(
                base_url=settings.OPENAI_BASE_URL,
                api_key=settings.OPENAI_API_KEY,
                model="gpt-4o", # Default to a good model
                temperature=0.7
            )
        # If neither local LLM is used nor OpenAI API key is set, self.llm remains None

    async def chat(self, user_message: str, history: str = "") -> str:
        if not self.llm:
            self._init_llm()
        
        if not self.llm:
            # If LLM is still not initialized after trying, return an error message
            return "系统提示: LLM 未配置。请在设置中将 USE_LOCAL_LLM 设为 True 或提供 OPENAI_API_KEY。"
        
        # Initialize chain only when llm is available
        if not self.chain:
            self.chain = self.prompt | self.llm | StrOutputParser()

        return await self.chain.ainvoke({"input": user_message, "history": history})

topic_consultant = TopicConsultant()
