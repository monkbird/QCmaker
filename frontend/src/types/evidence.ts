export type SourceKind = 'material' | 'web' | 'user' | 'derived' | 'simulation';
export type OriginKind = 'documented' | 'user_reported' | 'computed' | 'hypothesis' | 'simulation' | 'pending';
export type ContentState = 'empty' | 'draft' | 'complete';
export type ReviewState = 'pending' | 'approved' | 'changes_requested';
export type EvidenceState = 'missing' | 'partial' | 'verified' | 'not_applicable';

export interface EvidenceRef {
  source_kind: SourceKind;
  source_id: string;
  source_version: number;
  locator: string;
  excerpt?: string | null;
  origin_kind: OriginKind;
}

export interface EvidenceBlock { ref: EvidenceRef; text: string; table_position?: string | null; }
export interface MetricSpec {
  metric_id: string; name: string; unit: string; numerator?: string | null; denominator?: string | null;
  subject: string; comparison: string; sampling_method: string; time_range: string;
  value_kind: 'estimated' | 'measured' | 'simulated'; refs: EvidenceRef[];
}
export interface ProjectContext {
  project_id: string; region?: string | null; business_context?: string | null;
  personnel_constraints?: string | null; equipment_constraints?: string | null;
  activity_start?: string | null; activity_end?: string | null; topic_type?: string | null;
  objective_source?: string | null; standard_version?: string | null; source_notes?: string | null;
  revision: number;
}
export interface ChapterSnapshot {
  project_id: string; chapter_id: string; revision: number; path_version: string;
  content_blocks: Record<string, unknown>[]; metrics: MetricSpec[]; evidence_refs: EvidenceRef[];
  content_state: ContentState; review_state: ReviewState; evidence_state: EvidenceState;
  upstream_versions: Record<string, number>; stale: boolean; stale_reasons: string[];
}
export interface ArtifactSnapshot {
  artifact_id: string; project_id: string; content_version: number;
  upstream_versions: Record<string, number>; generated_at: string;
  artifact_kind: 'chart' | 'export'; operation_id: string; payload: Record<string, unknown>;
  stale: boolean; stale_reasons: string[];
}
