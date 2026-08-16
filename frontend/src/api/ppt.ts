import { api } from './client'
import type { PPTRequest, PPTResult } from '../types/api'
export const generatePpt = async (input:PPTRequest) => (await api.post<PPTResult>('/ppt/generate',input)).data
export const getPptDownloadUrl = (fileId:string) => `${api.defaults.baseURL ?? '/api'}/ppt/download/${encodeURIComponent(fileId)}`

