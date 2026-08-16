import { api } from './client'
import type { ConfigUpdate, ConfigView, ModelListResponse, ModelProvider, UsageView } from '../types/api'
export const getConfig = async () => (await api.get<ConfigView>('/config/')).data
export const updateConfig = async (input:ConfigUpdate) => (await api.post<ConfigView>('/config/update', input)).data
export const checkConnectivity = async (input:{provider:string;base_url?:string;api_key?:string;model?:string}) => (await api.post<{status:string;latency_ms:number;model:string;message:string}>('/config/check-connectivity', input)).data
export const getUsage = async () => (await api.get<UsageView>('/config/usage')).data
export const getProviders = async () => (await api.get<{providers:ModelProvider[]}>('/config/providers')).data.providers
export const getModels = async (input:{provider:string;base_url?:string;api_key?:string}) => (await api.post<ModelListResponse>('/config/models',input)).data
