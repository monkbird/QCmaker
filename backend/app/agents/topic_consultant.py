from __future__ import annotations

from backend.app.core.llm_gateway import chat
from backend.app.models.contracts import ChatMessage


class TopicConsultant:
    async def chat(self, user_message: str, history: list[ChatMessage] | None = None) -> str:
        messages = [
            {"role": "system", "content": "你是QC课题顾问。依据QC活动程序，帮助用户把问题转为对象、问题、目标可量化的规范课题。"},
            *[message.model_dump() for message in (history or [])],
            {"role": "user", "content": user_message},
        ]
        return await chat(messages)


topic_consultant = TopicConsultant()
