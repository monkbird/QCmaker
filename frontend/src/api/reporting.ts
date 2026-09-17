import { api } from './client'
import type { Preflight, ReportArtifact, ReportChapters } from '../types/reporting'
export const getReportChapters = async (project: string) => (await api.get<ReportChapters>(`/projects/${encodeURIComponent(project)}/chapters`)).data
export const getArtifacts = async (project: string) => (await api.get<{artifacts:ReportArtifact[]}>(`/projects/${encodeURIComponent(project)}/artifacts`)).data.artifacts
export const preflightChapters = async (project_id:string, chapter_revisions:Record<string,number>, chart_revisions:Record<string,number>) => (await api.post<Preflight>('/ppt/preflight',{project_id,chapter_revisions,chart_revisions})).data
export const exportChapters = async (project_id:string,chapter_revisions:Record<string,number>,chart_revisions:Record<string,number>,mode:'draft'|'confirmed',operation_id:string) => (await api.post<ReportArtifact>('/ppt/generate-from-chapters',{project_id,chapter_revisions,chart_revisions,mode,operation_id}, {timeout:180000})).data
export const createChapterChart = async (spec:{project_id:string;chapter_id:string;revision:number;metric_id:string;chart_type:string;aggregation:string},operation_id:string) => (await api.post<ReportArtifact>('/chapter-charts',{spec,operation_id})).data
