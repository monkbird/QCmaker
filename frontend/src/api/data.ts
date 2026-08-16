import { api } from './client'
import type { CleaningApplyRequest, CleaningPreviewResponse, DatasetResponse } from '../types/api'
export const uploadData = async (file:File) => { const body=new FormData(); body.append('file',file); return (await api.post<DatasetResponse>('/data/upload',body)).data }
export const getDataset = async (id:string) => (await api.get<DatasetResponse>(`/data/${id}`)).data
export const previewCleaning = async (input:CleaningApplyRequest) => (await api.post<CleaningPreviewResponse>('/data/preview',input)).data
export const applyCleaning = async (input:CleaningApplyRequest) => (await api.post<DatasetResponse>('/data/apply',input)).data
export const undoCleaning = async (dataset_id:string,base_revision:number) => (await api.post<DatasetResponse>('/data/undo',{dataset_id,base_revision})).data
export const confirmData = async (dataset_id:string,revision:number) => (await api.post<DatasetResponse>('/data/confirm',{dataset_id,revision})).data

