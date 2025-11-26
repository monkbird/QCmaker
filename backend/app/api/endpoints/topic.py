from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.app.agents.topic_consultant import topic_consultant

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    history: str = ""

class ChatResponse(BaseModel):
    response: str

@router.post("/chat", response_model=ChatResponse)
async def chat_with_consultant(request: ChatRequest):
    try:
        response = await topic_consultant.chat(request.message, request.history)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
