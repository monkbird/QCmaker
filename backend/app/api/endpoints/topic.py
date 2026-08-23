import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.core.llm_gateway import chat
from backend.app.core.security import verify_access_token
from backend.app.models.contracts import TopicChatRequest, TopicChatResponse, TopicEvaluation
from backend.app.services.rag import rag_service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_access_token)])

EVALUATION_PROMPT = """你是QC课题评估专家。依据 QC 小组活动程序与 SMART 原则，对给定课题逐维打分并给出改进建议。
五个维度各打 1-5 分（整数）：specific(具体性-对象和问题是否明确), measurable(可测量-目标是否量化), achievable(可实现-资源与周期是否现实), relevant(相关性-是否贴合岗位与方针), time_bound(时限性-是否有明确节点)。
只输出合法 JSON：{"specific":1,"measurable":2,"achievable":3,"relevant":4,"time_bound":5,"verdict":"一句话结论","suggestions":["建议1","建议2"]}。不要 Markdown。"""

CHAT_PROMPT = "你是QC课题顾问。请基于问题具体、简洁地引导用户形成可量化的QC课题。"


def _collect_references(documents) -> list[str]:
    references: list[str] = []
    seen: set[str] = set()
    for document in documents:
        snippet = document.page_content[:300].replace("\n", " ").strip()
        if snippet and snippet not in seen:
            seen.add(snippet)
            references.append(snippet)
    return references


async def _search_references(query: str, k: int = 3) -> list[str]:
    try:
        documents = await rag_service.search(query, k)
        return _collect_references(documents)
    except Exception:
        logger.info("rag references unavailable", exc_info=True)
        return []


class TopicEvaluateRequest(BaseModel):
    topic: str = Field(min_length=4, max_length=2000)


@router.post("/chat", response_model=TopicChatResponse)
async def chat_with_consultant(request: TopicChatRequest):
    references = await _search_references(request.message)
    system_prompt = CHAT_PROMPT
    if references:
        block = "\n".join(f"- {item}" for item in references)
        system_prompt += f"\n\n用户上传的参考资料（回答时可自然引用，不要虚构资料外的数据）：\n{block}"
    messages = [{"role": "system", "content": system_prompt}, *[item.model_dump() for item in request.history], {"role": "user", "content": request.message}]
    return TopicChatResponse(response=await chat(messages), references_used=len(references))


@router.post("/evaluate", response_model=TopicEvaluation)
async def evaluate_topic(request: TopicEvaluateRequest):
    references = await _search_references(request.topic)
    reference_block = "\n".join(f"- {item}" for item in references) if references else "（无可检索的历史资料）"
    prompt = f"课题：{request.topic}\n\n可参考的历史/内部资料：\n{reference_block}"
    raw = await chat([{"role": "system", "content": EVALUATION_PROMPT}, {"role": "user", "content": prompt}], role="topic")
    try:
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        evaluation = TopicEvaluation(
            specific=max(1, min(5, int(parsed["specific"]))),
            measurable=max(1, min(5, int(parsed["measurable"]))),
            achievable=max(1, min(5, int(parsed["achievable"]))),
            relevant=max(1, min(5, int(parsed["relevant"]))),
            time_bound=max(1, min(5, int(parsed["time_bound"]))),
            total=0,
            verdict=str(parsed.get("verdict", ""))[:500],
            suggestions=[str(item)[:300] for item in parsed.get("suggestions", [])][:8],
            references_used=len(references),
        )
        evaluation.total = evaluation.specific + evaluation.measurable + evaluation.achievable + evaluation.relevant + evaluation.time_bound
        return evaluation
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("topic evaluation parse failed: %s", exc)
        from backend.app.core.errors import AppException
        raise AppException("TOPIC_EVAL_FAILED", "评估结果解析失败，请重试或换用其他模型", 502) from exc
