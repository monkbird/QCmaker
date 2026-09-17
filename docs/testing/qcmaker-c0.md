# QCmaker C0 契约冻结

## 公共类型

后端公共类型位于 `backend/app/models/evidence.py`，前端镜像位于 `frontend/src/types/evidence.ts`。`EvidenceRef`要求项目、来源类别、来源ID、正整数版本及可显示定位；`origin_kind=documented`仅表示资料记载，不表示项目事实已核实。章节的 `review_state` 与 `evidence_state` 独立，审核通过不会把证据变成 verified。所有快照和资料版本独立递增，消费者必须校验 project_id。

四组可验证样例位于 `backend/tests/fixtures/qc_contracts/`：valid、conflict、missing-evidence、simulation。

## 数据库表契约

现有 v1 的 SQL 文本及 SHA-256 校验值保持不变。v2 由 `backend/app/repositories/qc_schema.py` 集中登记并由 `init_database()` 在一个事务内执行；导入模块不执行 DDL。表名及核心列如下：

| 表 | 核心列 |
|---|---|
| config_profiles | profile_id PK, name, payload_json, revision |
| config_credentials | credential_id PK, provider, base_url, secret |
| config_profile_state | 单行 id=1, active_profile_id, revision, legacy_migrated |
| materials | material_id PK, project_id, current_version |
| material_versions | (material_id, version) PK, original_path, metadata_json |
| material_parse_units | (material_id, version, unit_id) PK, locator, status, content_json |
| material_cleaning_previews | preview_id PK, project_id, material_id, base_version, operations_json, diff_digest, expires_at |
| material_events | event_id PK, project_id, material_id, old_version, new_version, changed_locators_json, reason |
| material_upload_operations | (project_id, idempotency_key) PK, request_hash, material_id, result_json |
| material_event_consumers | (event_id, consumer_name) PK, consumed_at, result_json |
| dataset_versions | (dataset_id, version) PK, rows_json, columns_json, report_json |
| dataset_material_links | (project_id, material_id, material_version, dataset_id) PK, dataset_version |
| project_contexts | project_id PK, context_json, revision |
| chapters | (project_id, chapter_id, revision) PK, snapshot_json |
| chapter_reviews | (project_id, chapter_id, revision) PK, review_state, reviewer_id, reviewed_at |
| source_dependencies | (project_id, consumer_type, consumer_id, source_id, source_version) PK |
| project_activity | event_id PK, project_id, event_type, payload_json |
| artifacts | artifact_id PK, project_id, artifact_kind, content_version, upstream_versions_json, stale, stale_reasons_json, payload_json, operation_id; UNIQUE(project_id, operation_id) |

迁移测试覆盖新库初始化、旧 v1 校验值保留和重复启动幂等。领域仓库应消费这些表，不在导入时自行建表；复杂领域对象以 validated JSON 保存，同时以项目、ID、revision/version 建索引。

## 已知限制

本阶段只冻结公共数据含义和持久化边界，不提供领域 API、加密凭据存储、跨项目授权策略或存量业务数据迁移；这些由后续领域包和集成包实现。
