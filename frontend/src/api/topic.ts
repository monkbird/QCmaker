import { api } from './client'
import type { ChatMessage } from '../types/api'
export const topicChat = async (message:string, history:ChatMessage[]) => (await api.post<{response:string}>('/topic/chat', {message, history})).data

