import type { EChartsOption } from 'echarts'
import type { ChapterSnapshot } from './evidence'
export interface PreflightIssue { code: string; message: string; severity: 'warning'|'error'; chapter_id?: string | null }
export interface Preflight { blocked: boolean; issues: PreflightIssue[] }
export interface ReportArtifact {
  artifact_id: string; project_id: string; artifact_kind: 'chart'|'export'; content_version: number;
  upstream_versions: Record<string,number>; generated_at: string; stale: boolean; stale_reasons: string[];
  payload: { option?: EChartsOption; file?: { file_id:string;display_name:string;expires_at:string }; preflight?: Preflight; snapshots?: ChapterSnapshot[] }
}
export interface ReportChapters { chapters: ChapterSnapshot[]; path: {chapter_id:string;title:string}[] }
