from fastapi import APIRouter

from backend.app.core.llm_gateway import chat
from backend.app.models.contracts import TopicChatRequest, TopicChatResponse

router = APIRouter()

@router.post("/chat", response_model=TopicChatResponse)
async def chat_with_consultant(request: TopicChatRequest):
    messages = [{"role": "system", "content": "你是QC课题顾问。请基于问题具体、简洁地引导用户形成可量化的QC课题。"}, *[item.model_dump() for item in request.history], {"role": "user", "content": request.message}]
    return TopicChatResponse(response=await chat(messages))
