import { api, llmApi } from './client'
import type { ConfigUpdate, ConfigView, ModelListResponse, ModelProvider, UsageView } from '../types/api'
export type ModelBinding = { service_id: string; model: string }
export type ServiceDraft = { service_id: string; provider: string; base_url: string; credential_id?: string | null; api_key?: string }
export type ConfigDraft = { name: string; default_model: ModelBinding | null; roles: Record<string, ModelBinding | null>; services: ServiceDraft[]; search: { provider: 'tavily'; credential_id?: string | null; api_key?: string } | null }
export type ConfigProfile = { profile_id:string; config_revision:number; active:boolean; draft:ConfigDraft; credential_configured:Record<string, boolean> }
export type ProbeRow = {role:string;service_id:string|null;provider:string|null;base_url:string|null;model:string|null;status:'passed'|'failed'|'missing';code?:string|null;message:string;latency_ms?:number|null}
export type ProbeReport = { draft_version:number; config_revision:number; passed:boolean; rows:ProbeRow[] }
export type SearchTestReport = { status:'not_configured'|'failed'|'empty'|'success'; message:string; results?: Array<{title:string;url:string}> }
export const getConfig = async () => (await api.get<ConfigView>('/config/')).data
export const updateConfig = async (input:ConfigUpdate) => (await api.post<ConfigView>('/config/update', input)).data
export const checkConnectivity = async (input:{provider:string;base_url?:string;api_key?:string;model?:string}) => (await llmApi.post<{status:string;latency_ms:number;model:string;message:string}>('/config/check-connectivity', input)).data
export const getUsage = async () => (await api.get<UsageView>('/config/usage')).data
export const getProviders = async () => (await api.get<{providers:ModelProvider[]}>('/config/providers')).data.providers
export const getModels = async (input:{provider:string;base_url?:string;api_key?:string;credential_id?:string|null}) => (await llmApi.post<ModelListResponse>('/config/models',input,{timeout:20000})).data
export const getProfiles = async () => (await api.get<{profiles:ConfigProfile[];active_profile_id:string|null;config_revision:number}>('/config/profiles')).data
export const saveProfile = async (input:{profile_id?:string;expected_revision:number;draft:ConfigDraft}) => (await api.post<ConfigProfile>('/config/profiles/save',input)).data
export const activateProfile = async (profileId:string, expected_revision:number) => (await api.post<ConfigProfile>(`/config/profiles/${encodeURIComponent(profileId)}/activate`,{expected_revision})).data
export const probeDraft = async (input:{draft_version:number;expected_revision:number;draft:ConfigDraft}) => (await llmApi.post<ProbeReport>('/config/probe-draft',input)).data
export const testSearch = async (input:{draft_version:number;expected_revision:number;draft:ConfigDraft}) => (await llmApi.post<SearchTestReport>('/search/test',input)).data
