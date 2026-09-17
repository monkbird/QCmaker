"""Transactional v2 QC schema. No DDL is executed on import."""
QC_SCHEMA_VERSION = 2

QC_MIGRATION_V2 = (
    "CREATE TABLE IF NOT EXISTS config_profiles(profile_id TEXT PRIMARY KEY, name TEXT NOT NULL, payload_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS config_credentials(credential_id TEXT PRIMARY KEY, provider TEXT NOT NULL, base_url TEXT, secret TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS config_profile_state(id INTEGER PRIMARY KEY CHECK(id=1), active_profile_id TEXT REFERENCES config_profiles(profile_id), revision INTEGER NOT NULL DEFAULT 1, legacy_migrated INTEGER NOT NULL DEFAULT 0 CHECK(legacy_migrated IN (0,1)))",
    "CREATE TABLE IF NOT EXISTS materials(material_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, current_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS material_versions(material_id TEXT NOT NULL REFERENCES materials(material_id), version INTEGER NOT NULL, original_path TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(material_id,version))",
    "CREATE TABLE IF NOT EXISTS material_parse_units(material_id TEXT NOT NULL, version INTEGER NOT NULL, unit_id TEXT NOT NULL, locator TEXT NOT NULL, status TEXT NOT NULL, content_json TEXT, error TEXT, PRIMARY KEY(material_id,version,unit_id), FOREIGN KEY(material_id,version) REFERENCES material_versions(material_id,version))",
    "CREATE TABLE IF NOT EXISTS material_cleaning_previews(preview_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, material_id TEXT NOT NULL, base_version INTEGER NOT NULL, operations_json TEXT NOT NULL, diff_digest TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS material_events(event_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, material_id TEXT NOT NULL, old_version INTEGER, new_version INTEGER NOT NULL, changed_locators_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS material_upload_operations(project_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, material_id TEXT, result_json TEXT, created_at TEXT NOT NULL, PRIMARY KEY(project_id,idempotency_key))",
    "CREATE TABLE IF NOT EXISTS material_event_consumers(event_id TEXT NOT NULL REFERENCES material_events(event_id), consumer_name TEXT NOT NULL, consumed_at TEXT NOT NULL, result_json TEXT, PRIMARY KEY(event_id,consumer_name))",
    "CREATE TABLE IF NOT EXISTS dataset_versions(dataset_id TEXT NOT NULL, version INTEGER NOT NULL, rows_json TEXT NOT NULL, columns_json TEXT NOT NULL, report_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(dataset_id,version))",
    "CREATE TABLE IF NOT EXISTS dataset_material_links(project_id TEXT NOT NULL, material_id TEXT NOT NULL, material_version INTEGER NOT NULL, dataset_id TEXT NOT NULL, dataset_version INTEGER, created_at TEXT NOT NULL, PRIMARY KEY(project_id,material_id,material_version,dataset_id))",
    "CREATE TABLE IF NOT EXISTS project_contexts(project_id TEXT PRIMARY KEY, context_json TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS chapters(project_id TEXT NOT NULL, chapter_id TEXT NOT NULL, revision INTEGER NOT NULL, snapshot_json TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(project_id,chapter_id,revision))",
    "CREATE TABLE IF NOT EXISTS chapter_reviews(project_id TEXT NOT NULL, chapter_id TEXT NOT NULL, revision INTEGER NOT NULL, review_state TEXT NOT NULL, reviewer_id TEXT, reviewed_at TEXT, note TEXT, PRIMARY KEY(project_id,chapter_id,revision))",
    "CREATE TABLE IF NOT EXISTS source_dependencies(project_id TEXT NOT NULL, consumer_type TEXT NOT NULL, consumer_id TEXT NOT NULL, source_id TEXT NOT NULL, source_version INTEGER NOT NULL, PRIMARY KEY(project_id,consumer_type,consumer_id,source_id,source_version))",
    "CREATE TABLE IF NOT EXISTS project_activity(project_id TEXT NOT NULL, event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS artifacts(artifact_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, artifact_kind TEXT NOT NULL, content_version INTEGER NOT NULL, upstream_versions_json TEXT NOT NULL, generated_at TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0 CHECK(stale IN (0,1)), stale_reasons_json TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', operation_id TEXT NOT NULL, UNIQUE(project_id,operation_id))",
    "CREATE INDEX IF NOT EXISTS idx_materials_project ON materials(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_chapters_project ON chapters(project_id,chapter_id,revision)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id,generated_at)",
)
