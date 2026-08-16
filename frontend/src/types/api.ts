import type { EChartsOption } from 'echarts'

export interface AppError { code: string; message: string; details?: Record<string, unknown>; request_id?: string }
export interface ConfigView { llm_provider:string; openai_base_url: string; openai_model: string; use_local_llm: boolean; local_llm_url: string; local_llm_model: string; max_budget_usd: number; has_openai_key: boolean; has_tavily_key: boolean; status: 'ready' | 'missing' | 'degraded'; config_revision: number }
export interface ConfigUpdate { llm_provider?:string; openai_api_key?: string; openai_base_url?: string; openai_model?: string; use_local_llm?: boolean; local_llm_url?: string; local_llm_model?: string; tavily_api_key?: string; max_budget_usd?: number }
export interface ModelProvider { id:string;name:string;region:'cn'|'global'|'local'|'custom';base_url:string;api_style:string;key_url?:string|null;docs_url?:string|null;verified_at:string }
export interface ModelListResponse { models:string[];source:'remote' }
export interface UsageView { budget_usd: string; reserved_usd: string; known_cost_usd: string; remaining_usd: string; unknown_cost: boolean; usage_by_model: Array<{provider:string;model:string;input_tokens:number;output_tokens:number;embedding_tokens:number;known_cost_usd:string}> }
export interface ChatMessage { role: 'user' | 'assistant'; content: string }
export interface DataRow { row_id: string; values: Record<string, string | number | boolean | null> }
export interface ColumnInfo { name:string; inferred_type:'string'|'number'|'percent'|'date'|'boolean'; missing_count:number; outlier_count:number; display_format:'plain'|'percent'|'date'|'datetime' }
export type CleaningAction = 'keep'|'drop_rows'|'median'|'forward_fill'|'convert_number'|'convert_percent'
export interface CleaningRule { action:CleaningAction; column?:string|null; row_ids:string[] }
export interface CleaningIssue { issue_type:'empty_row'|'total_row'|'missing'|'outlier'|'type_conversion'; column?:string|null; row_ids:string[]; suggested_actions:string[] }
export interface CleaningReport { mode:'detected'|'applied'|'undone'; issues:CleaningIssue[]; applied_rules:CleaningRule[]; removed_rows:number; filled_cells:number; outliers_detected:number; type_conversions:number }
export interface DatasetResponse { dataset_id:string; revision:number; confirmed_revision:number|null; restored_from_revision?:number|null; filename:string; columns:ColumnInfo[]; rows:DataRow[]; report:CleaningReport }
export interface CleaningApplyRequest { dataset_id:string; base_revision:number; rules:CleaningRule[] }
export interface CleaningPreviewResponse { dataset_id:string; base_revision:number; preview_rows:DataRow[]; report:CleaningReport }
export interface DiscussionSummary { problem:string; root_causes:string[]; countermeasures:string[]; summary:string }
export interface ChartRequest { chart_type:'bar'|'line'|'pie'; dataset_id:string; revision:number; x_axis:string; y_axis:string; aggregation?:'none'|'sum'|'mean'|'count' }
export interface ChartResponse { option:EChartsOption; processing:{aggregation:'none'|'sum'|'mean'|'count';converted_row_ids:string[];grouped_categories:number;warnings:string[]} }
export interface ChartRecommendation { chart_type:'bar'|'line'|'pie';x_axis:string;y_axis:string;reason:string }
export interface PPTResult { file_id:string;display_name:string;expires_at:string }
export interface PPTRequest { project_name:string;topic:string;data_summary:string;discussion_summary:DiscussionSummary;chart_images:string[] }
