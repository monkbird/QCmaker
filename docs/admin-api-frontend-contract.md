# QCmaker Admin API ↔ Frontend Contract

This contract is the frontend integration boundary for the v2 admin console. The browser only calls same-origin `/api/admin` endpoints with `credentials: include`; it never sends the business `x-api-token` on an admin request. All JSON responses use UTF-8 and `Cache-Control: no-store`.

## Shared response and error rules

Successful list responses use `{ items, total, limit, offset, total_is_estimate? }`. Cursor based endpoints may use `{ items, next_cursor }`. Dates are UTC ISO 8601 strings and the UI formats them for Asia/Shanghai. Decimal money values are strings. An error response is:

```json
{
  "code": "ERROR_CODE",
  "message": "面向管理员的说明",
  "request_id": "request-id",
  "details": {}
}
```

The frontend maps 401 to the login screen, 403 `ADMIN_CSRF_EXPIRED` to one `me` refresh and one retry, 503 `ADMIN_DISABLED`/`ADMIN_NOT_INITIALIZED` to an explicit setup state, and all other failures to a retryable inline error. The server must not return secrets, raw dataset rows, credentials, cookies, absolute paths, or unsanitized HTML.

## Authentication

`POST /api/admin/auth/login`

Request: `{ "username": string, "password": string }`.

Response:

```json
{
  "user": { "user_id": "...", "username": "admin", "is_active": true },
  "csrf_token": "opaque-token",
  "server_time": "2026-09-13T00:00:00Z",
  "idle_expires_at": "...",
  "absolute_expires_at": "..."
}
```

The server sets the host-only HttpOnly `qc_admin_sid` cookie with `Path=/api/admin`, `SameSite=Strict`, and the deployment-appropriate Secure flag. Login uses JSON and the strict same-origin check; it does not require a CSRF header.

`GET /api/admin/auth/me` returns the same session fields and rotates the CSRF generation only when its TTL has expired. It never counts as user activity.

`POST /api/admin/auth/activity` accepts `{}` and requires CSRF. The client sends `X-Admin-User-Activity: 1` only after an explicit user interaction.

`POST /api/admin/auth/logout` returns `{ "revoked": true }` and clears the same cookie attributes. Repeated logout is stable.

`POST /api/admin/auth/reauth` accepts `{ "current_password": string }` and returns `{ "reauthenticated_at": string }`.

`POST /api/admin/auth/change-password` accepts `{ "old_password": string, "new_password": string, "reason": string }` and returns `{ "relogin_required": true }`.

## Read models

`GET /api/admin/dashboard/overview` returns:

```json
{
  "health": { "status": "healthy|degraded|unavailable", "checks": [], "calculated_at": "...", "data_source": "...", "freshness": "fresh|stale|unknown" },
  "budget": { "limit_usd": "0.00", "known_cost_usd": "0.00", "reserved_usd": "0.00", "remaining_usd": "0.00", "usage_unknown_usd": "0.00", "provider_overrun_usd": "0.00", "progress_percent": null, "calculated_at": "...", "data_source": "...", "freshness": "..." },
  "usage_today": { "cost_usd": "0.00", "requests": 0, "input_tokens": 0, "output_tokens": 0, "embedding_tokens": 0, "calculated_at": "...", "data_source": "...", "freshness": "..." },
  "sessions": { "active": 0, "running": 0, "needs_recovery": 0, "calculated_at": "...", "data_source": "...", "freshness": "..." },
  "files": { "ready": 0, "missing": 0, "expired": 0, "calculated_at": "...", "data_source": "...", "freshness": "..." },
  "storage": { "used_bytes": 0, "free_bytes": 0, "calculated_at": "...", "data_source": "...", "freshness": "..." },
  "trend": [{ "bucket": "...", "cost_usd": "0.00", "tokens": 0, "requests": 0 }],
  "activity": [{ "id": "...", "level": "info|warning|error", "category": "usage|maintenance|discussion|ppt|rag|config|security|system", "message": "...", "operation_id": null, "context": {}, "created_at": "..." }]
}
```

`GET /api/admin/dashboard/trends?range=24h|7d|30d&metric=cost|tokens|requests` returns `{ items: TrendPoint[] }` with empty buckets filled.

`GET /api/admin/dashboard/activity?limit=&offset=&level=&category=` returns a paginated activity list.

`GET /api/admin/usage/summary?range=24h|7d|30d|all&from=&to=` returns `{ range, from, to, cost_usd, input_tokens, output_tokens, embedding_tokens, requests, usage_unknown_usd, provider_overrun_usd, overrun_cleared_usd, buckets: TrendPoint[], calculated_at, data_source, freshness }`.

`GET /api/admin/usage/by-model` returns rows with `{ provider, model, input_tokens, output_tokens, embedding_tokens, requests, cost_usd }`.

`GET /api/admin/budget/reservations` returns rows with `{ id, request_id, provider, model, amount_usd, status, created_at, expires_at, released_at, reason }`.

`GET /api/admin/datasets` returns rows with `{ dataset_id, filename, revision, confirmed_revision, row_count, column_count, expires_at, created_at, status }`; `GET /api/admin/datasets/{id}` returns `{ ...row, columns: [{ name, inferred_type }], quality: { issue_count, missing_cells, outliers, report_mode } }` and never returns raw row JSON.

`GET /api/admin/discussions` returns `{ session_id, project_id, topic, status, command_status, event_count, generation, lease_owner, lease_until, created_at, updated_at }`. Events and commands endpoints return safe, truncated summaries only.

`GET /api/admin/files` and `/api/admin/ppts` return `{ file_id, display_name, kind, status, size_bytes, created_at, expires_at, integrity_status }`.

`GET /api/admin/rag/projects` returns `{ project_id, name, document_count, chunk_count, legacy, freshness }`; documents return `{ document_id, filename, chunk_count, collection_count, created_at, metadata_summary }`; collections return `{ name, model_fingerprint, project_count, document_count, status }`.

`GET /api/admin/system/health`, `/logs`, `/storage` use the plan's `HealthView`, `LogChunk`, and `StorageView` fields. Log chunks are `{ lines: [{ created_at, level, message, truncated }], cursor, file_identity, freshness }`; the browser renders messages as text.

`GET /api/admin/security/sessions` returns safe session rows only. `GET /api/admin/security/settings` returns the flattened policy view `{ enabled, source, allowed_ips_configured, session_idle_minutes, session_absolute_hours, csrf_token_ttl_minutes, max_sessions, secrets }`; it never returns secret values. `GET /api/admin/config` returns `{ revision, fields: [{ key, value, label, source, editable, requires_restart, secret }], ... }`. `GET /api/admin/audit` returns safe `AuditLogView` rows with `operation_id` and `request_id`.

## Mutations

Every mutation except logout/activity/reauth must use `Idempotency-Key` when specified by the route. The frontend creates a UUID before sending and keeps it while a response is unresolved. A mutation response may be 200 or 202 and contains `{ operation_id, state, result?, error_code? }`; callers can poll `GET /api/admin/operations/{operation_id}`. The server must make repeated requests with the same actor/kind/key idempotent.

| UI action | Method and path | Required body |
|---|---|---|
| Reset overrun | POST `/budget/reset-overrun` | `reason`, `confirm_text` |
| Update budget | PUT `/budget/limit` | `expected_revision`, `max_budget_usd`, `reason`, `confirm_text` |
| Delete/purge dataset | DELETE `/datasets/{id}` / POST `/datasets/purge-expired` | `reason`, `confirm_text`, `scope: datasets`, `dry_run?` |
| Recover/end discussion | POST `/discussions/{id}/lease-recover` / `force-end` | `reason`, `confirm_text` |
| Delete PPT | DELETE `/ppts/{id}` | `reason`, `confirm_text` |
| Delete/purge RAG | DELETE `/rag/projects/{id}/documents/{doc}` / POST `/rag/projects/{id}/purge` | `reason`, `confirm_text`, `batch_size?` |
| Run maintenance/probe | POST `/system/maintenance` / `/system/probe/llm` | `scope`, `dry_run`, `reason`, `confirm_text` / `provider`, `model`, `reason`, `confirm_text` |
| Revoke session(s) | POST `/security/sessions/{id}/revoke` / `revoke-all` | `reason`, `confirm_text` |
| Rotate token | POST `/security/rotate-access-token` | `current_password`, `reason`, `confirm_text` |
| Update config | PUT `/config` | `expected_revision`, `values`, `reason` |

`GET /api/admin/usage/export.csv` uses the same filters as usage and returns UTF-8 BOM CSV with a server-generated Content-Disposition filename. The browser downloads the response without caching it.

## Frontend ownership notes

- Admin routes are outside `WizardProvider`; opening any `/admin/*` path must not call business endpoints or read the wizard snapshot.
- Polling and background log tail requests omit `X-Admin-User-Activity`; explicit clicks, filters, pagination, downloads, and mutation submissions may opt into it.
- Dangerous writes use the shared confirmation dialog: target, scope, impact, irreversible warning, reason, optional confirmation text, recent-password step when required, and operation status.
- All module pages provide loading, error, empty, and degraded/local freshness states. No page uses fixture data or reports an operation as successful before the server response confirms it.

Exact confirmation targets agreed with the backend are `provider_overrun` for the budget reset, `MAX_BUDGET_USD` for the budget limit, `datasets` for expired dataset cleanup, the dataset/session/file/document/project id for scoped actions, `other_sessions` for revoking other sessions, and `API_ACCESS_TOKEN` for token rotation. The frontend preserves the modal idempotency key in the request header.
