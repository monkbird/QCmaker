# Admin security implementation report

本次实现覆盖管理员认证基础设施、数据库管理表、审计与操作服务，以及本机密码工具和恢复流程。管理身份以 `admin_users` 为数据库唯一权威；环境变量只参与首次 bootstrap。密码使用 PBKDF2-HMAC-SHA256（至少 600000 次迭代和随机盐），会话只在数据库保存 SHA-256 token hash，CSRF 令牌由受保护本机密钥按会话派生。

已完成的安全边界包括：独立 `ADMIN_ENABLED` 开关和 fail-closed bootstrap；空闲/绝对会话期限；用户活动与轮询请求分离；Origin、JSON Content-Type、CSRF、重复 Cookie/请求头校验；生产 HTTPS 与受限本地开发 Cookie 例外；可信代理 IP 和 CIDR 白名单；持久化登录/重新认证限流；改密竞态复核、全会话吊销和原子审计。

审计服务提供事务内 `record_audit_tx`、查询脱敏、事件写入和 `purge_retention`。审计清理固定启动 cutoff，先持久化 `AUDIT_RETENTION_PURGE/REQUESTED`，删除与成功结果在同一事务中完成；失败回滚删除并记录 FAILED，审计不可用时返回 unknown。操作服务保存安全意图和规范化请求 hash，敏感值以指纹区分幂等请求而不落明文；重试使用原 operation id、显式安全 kind 白名单和 `admin_operation_attempts` 中的哈希 retry key。凭据、令牌、配置更新、模型探测和审计留存不标记为可重试，避免重放秘密或产生重复费用。

涉及文件：

- `backend/app/core/admin_security.py`
- `backend/app/services/audit.py`
- `backend/app/services/admin_operations.py`
- `backend/app/models/admin_contracts.py`
- `backend/app/api/endpoints/admin/auth.py`
- `backend/app/api/endpoints/admin/__init__.py`
- `backend/app/repositories/database.py`
- `scripts/gen_admin_password.py`
- `scripts/admin_local_recover.py`
- `backend/tests/test_admin_security.py`
- `backend/tests/test_admin_origin_boundary.py`

验证结果：

- `python -m pytest backend/tests/test_admin_security.py backend/tests/test_admin_origin_boundary.py backend/tests/test_admin_data_cleanup.py backend/tests/test_admin_data_metrics.py backend/tests/test_admin_rag_metadata.py backend/tests/test_admin_log_boundary.py -q`：30 passed。
- `python -m ruff check`（上述实现文件和测试）：通过。
- 当前验证未覆盖完整后端和浏览器端到端流程；这些检查由根代理继续执行。

待集成事项：数据库 v1 checksum 已包含 `admin_operation_attempts`；已有旧 checksum 的本地运行库必须按根代理的隔离运行库流程重建，生产库应由正式迁移流程处理。数据维护/操作路由仍需完成审计失败 fail-closed、清理 savepoint 失败回滚、过期清理失败状态和超时重试 worker 的独立验收；这些不在本安全基础实现的修改范围内。
