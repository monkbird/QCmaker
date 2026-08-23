import { llmApi } from './client'
import type { ChatMessage, RagIngestResult, TopicChatResponse } from '../types/api'
export const topicChat = async (message:string, history:ChatMessage[]) => (await llmApi.post<TopicChatResponse>('/topic/chat', {message, history})).data
export const ingestDocument = async (file:File) => { const form = new FormData(); form.append('file', file); return (await llmApi.post<RagIngestResult>('/rag/ingest', form)).data }
