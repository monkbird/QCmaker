# 配置方案独立审查（2026-09-16）

审查范围为 `backend/app/models/config_profiles.py`、`config_profile_repository.py`、`services/model_roles.py`、`api/endpoints/config.py`、`core/config.py` 及 `frontend/src/pages/ConfigPage.tsx`、`frontend/src/api/config.ts`，逐项对照 01 计划的多方案运行时、凭据隔离、环境锁、旧配置迁移、草稿探测和页面保存/切换要求。

## 集成复核状态

以下记录是修复前审查。随后已重写 ConfigPage，使用实际 service_id、统一方案保存、切换后完整恢复草稿；多服务凭据独立持久化，活动方案存在时旧模型写入接口返回冲突，模型描述消费活动快照；搜索凭据状态与服务级模型刷新已接入。配置回归测试及新界面浏览器烟测通过。真实外部模型和搜索成功调用仍未以用户付费凭据验收。

## 原阻塞问题

1. **旧配置迁移只保存第一个服务的凭据（高）**。`migrate_legacy()` 会为 `provider_ids` 创建多个 `ServiceDraft`，但落库时只取 `draft.services[0]` 写入 `config_credentials`；角色绑定到其他服务商时，其 `credential_id` 为空且密钥也不在方案 JSON 中。迁移完成后这些角色无法解析，表现为 `ROLE_MODEL_KEY_MISSING`。应逐个服务保存凭据并回写各自引用，或明确将无凭据服务标为缺失而不把迁移置为完整成功。

2. **命名方案保存页面会生成无效的角色服务引用（高）**。`ConfigPage.saveNamedProfile()` 把服务声明为 `service_id: "default"`，却把角色绑定的 `service_id` 写成 `provider`（如 `openai|model` 中的 `openai`）。后端 `ConfigDraft.validate_services()` 要求绑定引用已声明服务，因此只要存在角色模型分工，保存请求会被拒绝。页面需将角色绑定映射到实际 service_id，或为每个 provider 建立服务条目。

3. **切换方案只切换服务端活动ID，不恢复页面草稿（高）**。`switchProfile()` 成功后只更新 `selectedProfile`、`profileRevision` 和 dirty 状态，没有把返回的 `draft` 写回 Form，也没有更新 `roleModels`、主模型地址或搜索密钥状态。用户看到的表单仍是旧方案，之后保存可能覆盖刚切换的方案，违背“保存和恢复”。

4. **顶部“保存并继续”和角色/凭据保存仍写旧 `.env` 路径（高）**。`save()`、`saveRoles()`、`saveCredential()` 调用 `updateConfig()`，而不是命名方案仓库事务；它们更新 `Settings`/`.env`，不会更新活动 profile。页面显示已保存并继续时，运行时事实来源仍可能是另一套数据库方案，形成双写分叉。

5. **遗留 `/config/update` 未执行并发修订和环境锁检查（高）**。`update_config()` 调用 `update_settings(payload)` 时未传 `expected_revision`；`update_settings()` 只有在传入期望修订号时才检查 `key in os.environ`。因此旧接口可覆盖部署环境锁定项，也可丢失并发更新。该兼容接口必须接入统一修订/环境锁入口，或只允许非模型部署字段。

## 重要但非首个阻塞点

6. **`describe_target()` 不消费运行时快照**。它始终调用 `resolve_role_target(role)` 的旧 Settings 路径；若调用方在一次请求中已取得 `RuntimeSnapshot`，描述结果可能与实际调用目标不一致。应增加 snapshot 参数并复用同一解析结果。

7. **配置列表的凭据状态不覆盖搜索凭据**。`_view()` 只遍历 `draft.services` 构造 `credential_configured`，没有登记 `draft.search.credential_id`；前端无法准确展示 Tavily 凭据是否已保存。

8. **页面提示与部署边界不一致**。`ConfigPage` 仍显示“密钥仅保存在本机”，而 01 计划要求远程部署不得笼统声称只存本机；实际仓库凭据保存在服务端 SQLite。应改为“保存在当前部署的服务端，不在页面回显”，并根据部署模式决定更具体提示。

## 已核对的正向实现

`ProfileView` 的 payload 会移除服务和搜索 `api_key`；`RuntimeSnapshot` 使用冻结模型并提供深拷贝；`probe-draft` 按服务地址/模型/API 风格/密钥合并重复探测，并返回逐角色状态；`ConfigDraft` 校验服务 ID 唯一和绑定完整。这些实现仍受上述页面接线、迁移凭据和旧接口旁路影响，不能单独视为多方案运行时已闭环。

## 审查结论

在修复第 1—5 项并补充“关闭并重建客户端后恢复活动方案、环境锁拒绝、迁移多服务凭据、页面真实切换/保存”的回归前，01 配置包不应放行到全流程验收。审查未修改业务代码。
