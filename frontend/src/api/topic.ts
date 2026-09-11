import { api, llmApi } from './client';
import type { ChatMessage, RagIngestResult, TopicChatResponse } from '../types/api';
export const topicChat = async (message: string, history: ChatMessage[], projectId: string) => (await llmApi.post<TopicChatResponse>('/topic/chat', { message, history: history.slice(-50), project_id: projectId })).data;
export const ingestDocument = async (file: File, projectId: string) => { const form = new FormData(); form.append('file', file); form.append('project_id', projectId); return (await llmApi.post<RagIngestResult>('/rag/ingest', form)).data; };
export const listDocuments = async (projectId: string) => (await api.get<{
    documents: RagIngestResult[];
}>('/rag/documents', { params: { project_id: projectId } })).data.documents;
export const deleteDocument = async (documentId: string, projectId: string) => { await api.delete(`/rag/documents/${encodeURIComponent(documentId)}`, { params: { project_id: projectId } }); };
