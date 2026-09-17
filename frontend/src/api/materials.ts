import {api} from './client'; import type {MaterialItem,MaterialVersion,ParseManifest} from '../types/materials'
export const listMaterials=async(projectId:string)=>(await api.get<{items:MaterialItem[];next_cursor:string|null}>(`/projects/${projectId}/materials`)).data
export const uploadMaterial=async(projectId:string,file:File,onProgress?:(n:number)=>void)=>{const body=new FormData();body.append('file',file);return (await api.post<MaterialVersion>(`/projects/${projectId}/materials`,body,{onUploadProgress:e=>onProgress?.(e.loaded)})).data}
export const getParseManifest=async(projectId:string,id:string,version:number)=>(await api.get<ParseManifest>(`/projects/${projectId}/materials/${id}/parse`,{params:{version}})).data
export const previewCleaning=async(projectId:string,id:string,base_version:number,operations:CleaningOperation[])=>(await api.post<CleaningPreview>(`/projects/${projectId}/materials/${id}/cleaning-preview`,{base_version,operations})).data
export const applyCleaning=async(projectId:string,id:string,payload:{preview_id:string;diff_digest:string;confirmed_operation_ids:string[]})=>(await api.post<CleaningReceipt>(`/projects/${projectId}/materials/${id}/cleaning-apply`,payload)).data
export const undoCleaning=async(projectId:string,id:string,base_version:number,restore_version:number)=>(await api.post<CleaningReceipt>(`/projects/${projectId}/materials/${id}/cleaning-undo`,{base_version,restore_version})).data
export type CleaningOperation={operation_id:string;category:'document'|'data'|'evidence';target_locator:string;before:unknown;after:unknown;reason:string;risk:'low'|'high'}
export type CleaningPreview={preview_id:string;project_id:string;material_id:string;base_version:number;operations:CleaningOperation[];diff_digest:string;expires_at:string}
export type CleaningReceipt={version:number;parent_version:number;applied_operation_ids:string[];event_id:string}
