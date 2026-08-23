import axios, { AxiosError } from 'axios'
import type { AppError } from '../types/api'

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api', timeout: 30000 })
export const llmApi = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api', timeout: 180000 })
const apiToken = import.meta.env.VITE_API_TOKEN
if (apiToken) { api.defaults.headers.common['x-api-token'] = apiToken; llmApi.defaults.headers.common['x-api-token'] = apiToken }
for (const client of [api, llmApi]) client.interceptors.response.use((response) => response, (error: AxiosError<AppError>) => {
  const payload = error.response?.data
  const normalized: AppError = payload?.code ? payload : { code: error.code === 'ECONNABORTED' ? 'NETWORK_TIMEOUT' : 'NETWORK_ERROR', message: error.code === 'ECONNABORTED' ? '请求超时，请稍后重试' : '网络连接失败，请检查后端服务' }
  return Promise.reject(normalized)
})

export function errorMessage(error: unknown): string { return typeof error === 'object' && error !== null && 'message' in error ? String(error.message) : '操作失败' }

