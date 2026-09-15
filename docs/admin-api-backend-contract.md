# QCmaker 管理后台后端接口契约

本文固定管理数据接口与服务层的边界，供认证、前端和管理数据实现共同使用。路由由应用统一挂载在 `/api/admin`；本文件对应的聚合路由只负责非认证业务，认证与会话路由另行挂载。除登录外，所有请求均要求管理员会话和 CSRF（由管理认证依赖统一执行）。

## 通用规则

- JSON 成功响应使用明确字段；列表统一返回 `{items,total,limit,offset}`。`total_is_estimate` 仅在真实总数无法快速取得时返回 `true`。
- 时间一律使用带时区的 UTC ISO 8601 字符串；查询区间采用 `[from,to)` 半开区间。金额一律以十进制字符串返回，避免浮点误差。
- 响应只返回管理页面需要的白名单字段。数据库原始行、数据集 `raw_rows_json/current_rows_json`、令牌、密码、密钥、绝对路径和未脱敏 metadata 不得出站。
- 列表默认 `limit=50`，最大 `limit=200`，稳定排序必须包含唯一键。日志和 CSV 使用自己的上限。
- 错误沿用 `AppException` 的统一形状：`{"code":"...","message":"...","details":{},"request_id":"..."}`。
- 外部存储写操作先记录 operation intent；没有可用 operation 服务时，路由必须返回依赖错误，不能报告虚假的成功。

## 只读接口

### 看板和用量

`GET /dashboard/overview` 返回：

```json
{
  "health": {"status":"healthy|degraded|unavailable","checks":[],"calculated_at":"...","data_source":"sqlite|filesystem|chroma","freshness":"fresh|stale|unknown"},
  "budget": {"limit_usd":"0.00","known_cost_usd":"0.00","reserved_usd":"0.00","remaining_usd":"0.00","usage_unknown_usd":"0.00","provider_overrun_usd":"0.00","progress_percent":null,"calculated_at":"...","data_source":"sqlite","freshness":"fresh"},
  "usage_today": {"cost_usd":"0.00","requests":0,"input_tokens":0,"output_tokens":0,"embedding_tokens":0,"calculated_at":"...","data_source":"sqlite","freshness":"fresh"},
  "sessions": {"active":0,"running":0,"needs_recovery":0,"calculated_at":"...","data_source":"sqlite","freshness":"fresh"},
  "files": {"ready":0,"missing":0,"expired":0,"calculated_at":"...","data_source":"sqlite|filesystem","freshness":"fresh"},
  "storage": {"used_bytes":0,"free_bytes":0,"calculated_at":"...","data_source":"filesystem","freshness":"fresh"},
  "trend": [], "activity": []
}
```

`GET /dashboard/trends?range=24h|7d|30d&metric=cost|tokens|requests` 返回 `{items:[{bucket,cost_usd,tokens,requests}]}`，固定粒度并补齐空桶。

`GET /dashboard/activity` 支持 `level`, `category`, `limit`, `offset`，返回去重后的 `operation_events`，context 仅保留安全摘要。

`GET /usage/summary?range=24h|7d|30d|all&from=&to=` 返回 `{range,from,to,cost_usd,input_tokens,output_tokens,embedding_tokens,requests,usage_unknown_usd,provider_overrun_usd,overrun_cleared_usd,buckets,calculated_at,data_source,freshness}`。未知占用和供应商超额永远单独列出。

`GET /usage/by-model` 支持 provider/model/time/pagination，返回 `{items:[{provider,model,input_tokens,output_tokens,embedding_tokens,requests,cost_usd}],total,limit,offset}`。

`GET /budget/reservations` 支持 status/time/pagination，返回登记账本字段 `{id,request_id,provider,model,amount_usd,status,created_at,expires_at,released_at,reason}`。当前 schema 没有的后置字段以 `null` 表示，不能猜测释放时间。

`GET /usage/export.csv` 使用与 summary/by-model 相同的过滤器，最大 100000 行和 90 天，按 `created_at,id` 排序。响应为 UTF-8 BOM，固定列 `time,provider,model,input_tokens,output_tokens,embedding_tokens,cost_usd,request_id`；文本字段以 `=`, `+`, `-`, `@` 开头时增加单引号。

### 数据集、会话和成果

`GET /datasets` 返回 `{items:[{dataset_id,filename,revision,confirmed_revision,row_count,column_count,expires_at,created_at,status}],total,limit,offset}`。状态为 `active|expired`。

`GET /datasets/{dataset_id}` 返回列表字段加 `columns:[{name,inferred_type,missing_count,outlier_count,display_format}]` 和 `quality:{issue_count,missing_cells,outliers,report_mode,removed_rows,filled_cells,type_conversions}`；永不返回任何原始行内容。

`GET /discussions` 返回 `{items:[{session_id,project_id,topic,status,command_status,event_count,generation,lease_owner,lease_until,created_at,updated_at}],total,limit,offset}`。合法终态仅 `finished|cancelled`；执行中状态由命令和租约派生。

`GET /discussions/{id}/events` 返回 `{items:[{event_seq,event_type,client_message_id,created_at,summary}],total,limit,offset}`；`summary` 做长度限制和 PII 脱敏。

`GET /discussions/{id}/commands` 返回 `{items:[{client_message_id,status,picked_at,completed_at,payload_summary,error_summary}],total,limit,offset}`；不回显完整 payload/error。

`GET /files` 与 `GET /ppts` 返回 `{items:[{file_id,display_name,kind,status,size_bytes,created_at,expires_at,integrity_status}],total,limit,offset}`。登记表是可下载记录的唯一来源；目录孤儿只在独立对账信息中体现，绝不制造登记。

`GET /rag/projects` 返回项目级 `{project_id,name,document_count,chunk_count,legacy,freshness}`；`GET /rag/projects/{project_id}/documents` 返回 `{document_id,filename,chunk_count,collection_count,created_at,metadata_summary}`。两者都必须跨所有 `qc_` collection 按 metadata `project_id` 过滤，不能初始化 embedding client。

`GET /rag/collections` 返回只读 `{name,model_fingerprint,project_count,document_count,status}`；collection 删除不属于本接口。

### 系统、日志、安全和审计查询

`GET /system/health` 只检查进程、SQLite/WAL、固定目录和 Chroma metadata，不发模型请求。`GET /system/storage` 返回 `data`, `generated_ppts`, `logs` 三个目录的 `{path_label,exists,used_bytes,free_bytes,status}`，不暴露绝对路径。

`GET /system/logs` 只允许固定 `backend/logs/app.log` 和明确轮转文件，支持 level/tail/cursor/max_bytes/include_rotated。返回 `{lines:[{created_at,level,message,truncated}],cursor,file_identity,freshness}`；URL 参数、Authorization、Cookie、token、密钥模式和多行异常在服务端脱敏。

`GET /security/sessions`、`GET /security/settings`、`GET /config`、`GET /audit`、`GET /operations/{operation_id}` 由各自安全/配置/审计/操作服务提供安全白名单视图。数据聚合路由只做协议适配，不绕过这些服务。

## 写接口

除 logout/activity/reauth 外，写接口的确认字段、CSRF、近期再认证、幂等键和 operation_id 由管理服务统一裁决。SQL 内写操作必须与审计在同一事务中完成；外部文件/Chroma 操作返回 `pending|running|succeeded|partial|failed` 的真实状态。

- `POST /budget/reset-overrun`：只将 `provider_overrun` 置为 `overrun_cleared`，不删除 usage_events，不释放未知占用。
- `PUT /budget/limit`：接受 `expected_revision,max_budget_usd,reason`，先校验候选值，冲突返回 409。
- `DELETE /datasets/{id}` 与 `POST /datasets/purge-expired`：仅作用于 datasets scope；活动引用按契约跳过或返回 409。
- `POST /discussions/{id}/lease-recover` 与 `/force-end`：委托 discussion_session 的 generation/租约事务接口；旧 worker 不得写回。
- `GET /ppts/{id}/download`：先查登记记录、过期和固定目录边界，再返回文件；`DELETE /ppts/{id}` 删除失败时保留登记并返回 partial/failed。
- `DELETE /rag/projects/{id}/documents/{document_id}` 与 `POST /rag/projects/{id}/purge`：委托 metadata-only RAG 服务跨 collection 分批执行；`__legacy_unassigned__` 禁止项目批量删除。
- `POST /system/maintenance`：scope、dry_run、reason、confirm_text、idempotency_key，返回每个 scope 的 attempted/succeeded/skipped/failed/unknown。
- `POST /system/probe/llm`：显式联网探测，必须单独预算、超时、审计；健康接口绝不隐式探测。
- `PUT /config`：委托候选 Settings 校验和 expected_revision/env_override 检查；失败不得污染文件或内存。
