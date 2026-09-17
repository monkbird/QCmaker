export type MaterialVersion={project_id:string;material_id:string;version:number;filename:string;size_bytes:number;original_sha256:string;parse_status:string;readiness:string;review_status:string}
export type ParseRegion={region_id:string;kind:string;text:string;status:string;table_cells:string[][];method:string;confidence?:number|null}
export type ParseUnit={unit_id:string;kind:string;ordinal:number;locator:string;status:string;issues:string[];regions:ParseRegion[]}
export type ParseManifest={material_id:string;version:number;units_total:number;units_completed:number;units_failed:number;units_pending:number;coverage_complete:boolean;readiness:string;review_status:string;units:ParseUnit[];next_cursor:string|null}
export type MaterialItem={material_id:string;filename:string;version:number}
export type CleaningOperation={operation_id:string;category:'document'|'data'|'evidence';target_locator:string;before:unknown;after:unknown;reason:string;risk:'low'|'high'}
export type CleaningPreview={preview_id:string;project_id:string;material_id:string;base_version:number;operations:CleaningOperation[];diff_digest:string;expires_at:string}
