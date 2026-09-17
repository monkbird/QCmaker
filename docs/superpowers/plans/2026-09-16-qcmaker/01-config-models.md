# 配置方案、角色路由与真实连接验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持命名配置保存和恢复、默认模型可选、按角色检查能力，以及基于未保存草稿的统一真实模型调用验证。

**Architecture:** 配置方案引用独立服务凭据，保存和激活采用同一数据库事务；运行时通过不可变快照解析目标，禁止调用途中读取到另一方案。模型测试复用实际调用适配和计费边界；配置页统一保存，并分别展示模型和搜索验证结果。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、httpx、现有 LangChain OpenAI 客户端；React、TypeScript、Ant Design、Vitest、pytest。沿用仓库依赖，不自行升级或添加依赖。

**Spec:** `docs/QCmaker修改需求汇总与规划.md` 第3.1—3.4节、第4.2节中基本读取不依赖向量化的要求。本包只承担配置及模型能力，搜索执行和资料读取由对应包实现。

## Global Constraints

- 本轮仅编写规划，不执行以下实施步骤，不修改业务代码，不提交 Git。
- 已确认要求：默认主模型可选；缺少配置必须指出具体角色或能力。
- 已确认要求：保留底部“测试连接”作为统一测试入口，不新增角色旁的调用测试按钮。
- 已确认要求：测试基于当前待保存配置；相同服务地址、凭据和模型可合并；未选用模型不批量调用。
- 已确认要求：密钥不回显；远程部署不得笼统声称“只存本机”。
- 用户明确不加入“角色刷新按钮强制重新拉取并显示获取时间”修改项。
- 本文的字段、事务和路由属于实施设计建议，须经00契约门禁冻结；不把建议方案写成已经实现的能力。
- 除“当前依据”中明确核对过的既有路径和行为外，本文所有新增文件路径、接口、类型、函数、错误码及测试均为拟议未来设计。本文不安排任何子代理立即修改代码；后续实施须由用户另行安排。
- 本包日期、接口编号、测试断言为工程标识，保留准确值。业务宣传中的“xx”规则不替换工程契约。

---

## 1. 当前依据、范围及文件归属

静态核对发现：`core/config.py` 已有原子写文件、配置修订号和环境变量覆盖保护；`model_roles.py` 已有八个角色及“跟随默认”规则，但本地总开关优先于显式角色，缺默认密钥仍提示 OpenAI Key。`clients.py` 实际聊天只创建 OpenAI 兼容客户端，目录收录 Anthropic 不代表原生消息接口可用。`config.py` 的连接测试只测一个模型，本地只请求 `/api/tags`，不属于真实生成验证。`topic.py` 普通聊天未传角色，评估、清洗、图表和研讨已有角色参数。以下步骤保留已有预算、隐私及出站请求保护。

相对路径均以 `E:/Python/work/QCmaker` 为根。

| 排他归属 | 文件 | 职责 |
|---|---|---|
| 本包修改 | `backend/app/core/config.py` | 活跃方案读取、遗留设置兼容、配置修订号 |
| 本包修改 | `backend/app/core/clients.py` | 协议适配、客户端缓存、独立向量能力检查 |
| 本包修改 | `backend/app/core/llm_gateway.py` | 实际聊天和最小探测共用调用与计费边界 |
| 本包修改 | `backend/app/services/model_roles.py` | 草稿/运行时快照解析、角色就绪检查 |
| 本包修改 | `backend/app/services/model_providers.py` | 目录与实际支持协议区分 |
| 本包修改 | `backend/app/api/endpoints/config.py` | 方案接口、草稿验证接口、遗留接口兼容 |
| 本包修改 | `frontend/src/pages/ConfigPage.tsx` | 统一草稿、保存切换、模型和搜索结果呈现 |
| 本包修改 | `frontend/src/api/config.ts` | 方案及测试请求封装 |
| 本包新增，经00冻结 | `backend/app/models/config_profiles.py` | 配置专属模型、内部快照和结果模型 |
| 本包新增，经00冻结 | `backend/app/repositories/config_profile_repository.py` | 方案和凭据的事务访问、幂等迁移 |
| 本包新增 | `backend/tests/test_config_profiles.py` | 命名方案、保存、修订冲突和迁移 |
| 本包新增 | `backend/tests/test_config_role_capabilities.py` | 角色与能力解析、无默认模型 |
| 本包新增 | `backend/tests/test_config_draft_probe.py` | 草稿去重、真实调用路径和逐角色失败 |
| 本包新增 | `frontend/src/test/configProfiles.test.tsx` | 保存、切换、失效与请求乱序 |
| 本包只读回归 | `backend/tests/test_config_update.py`、`test_multi_model.py`、`test_model_providers.py`、`test_config_review_integration.py` | 旧配置、管理端和多角色兼容，涉及跨模块断言由集成包修改 |

不得并发修改：`backend/app/models/contracts.py`、`backend/app/repositories/database.py`、`backend/main.py`、`frontend/src/types/api.ts`、`frontend/src/routes/router.tsx`、`frontend/src/context/*`、`frontend/src/storage/db.ts`、所有 package/lock/requirements 文件。建表迁移、启动初始化、公共类型、向导门禁及管理端兼容由00/集成包统一接入。其他包调用网关，不修改本包文件。每个任务结束提交文件差异和验收记录供复核，本计划不安排 Git 提交。

## 2. 00门禁要冻结的契约

下列为具体拟议契约；00修改命名时必须同步本文件及消费包，禁止各包自建近似版本。

```python
# models/config_profiles.py；此处省略的只有 import，不省略业务字段
RoleId = Literal['moderator', 'researcher', 'analyst', 'critic', 'writer', 'topic', 'data', 'chart']

class ModelBinding(BaseModel):
    service_id: str
    model: str

class ServiceDraft(BaseModel):
    service_id: str
    provider: str
    base_url: str
    credential_id: str | None = None
    api_key: SecretStr | None = None  # 仅输入；空字符串保留旧值，不表示删除

class SearchBinding(BaseModel):
    provider: Literal['tavily'] = 'tavily'
    credential_id: str | None = None
    api_key: SecretStr | None = None  # 同样只允许输入

class ConfigDraft(BaseModel):
    name: str
    default_model: ModelBinding | None = None
    roles: dict[RoleId, ModelBinding | None] = Field(default_factory=dict)
    services: list[ServiceDraft] = Field(default_factory=list)
    search: SearchBinding | None = None

class ProfileSaveRequest(BaseModel):
    profile_id: str | None = None  # None=另存为新命名方案
    expected_revision: int
    draft: ConfigDraft

class ProbeRequest(BaseModel):
    draft: ConfigDraft
    draft_version: int  # 浏览器单调递增；编辑、切换、发起新测试都递增
    expected_revision: int  # 绑定服务端已保存凭据版本

class CapabilityIssue(BaseModel):
    role: str  # 角色名、default 或 embeddings
    code: str
    message: str

class ProbeRow(BaseModel):
    role: str
    service_id: str | None
    provider: str | None
    base_url: str | None
    model: str | None
    status: Literal['passed', 'failed', 'missing']
    code: str | None = None
    message: str
    latency_ms: int | None = None

class ProbeReport(BaseModel):
    draft_version: int
    config_revision: int
    passed: bool
    rows: list[ProbeRow]

class ProfileView(BaseModel):
    profile_id: str
    config_revision: int
    active: bool
    draft: ConfigDraft  # 输出前删除所有 api_key 字段，不使用 SecretStr 掩码代替删除
    credential_configured: dict[str, bool]  # credential_id -> 是否已存凭据

class RuntimeSnapshot(BaseModel):
    config_revision: int
    draft: ConfigDraft  # 仅后端内部；已绑定和解析密钥，绝不作为响应返回
```

运行接口：

```python
# config_profile_repository.py
def list_profiles() -> list[ProfileView]: ...
def save_and_activate(request: ProfileSaveRequest) -> ProfileView: ...
def activate(profile_id: str, expected_revision: int) -> ProfileView: ...
def active_snapshot() -> RuntimeSnapshot: ...
def resolve_draft(draft: ConfigDraft, expected_revision: int) -> RuntimeSnapshot: ...
def migrate_legacy(settings: Settings) -> None: ...

# model_roles.py；已有 ModelTarget 保留，并扩展 service_id、api_style 字段
def resolve_role_target(role: str | None, *, snapshot: RuntimeSnapshot | None = None) -> ModelTarget: ...
def check_capabilities(roles: list[str], *, snapshot: RuntimeSnapshot | None = None) -> list[CapabilityIssue]: ...

# llm_gateway.py：旧调用保持可用，新包统一传明确 role
async def chat(messages: list[dict[str, str]], role: str | None = None) -> str: ...
async def probe_target(target: ModelTarget) -> dict[str, object]: ...
# probe_target 返回 {latency_ms: int, message: str}；失败抛带安全错误码的 AppException

# api/endpoints/config.py
async def probe_draft(request: ProbeRequest) -> ProbeReport: ...
```

以上 `...` 是类型签名展示，不是实现占位；具体算法、事务及错误行为在任务内定义。

HTTP拟议接口：`GET /api/config/profiles` 返回 `{profiles: ProfileView[], active_profile_id: string|null, config_revision: number}`；`POST /api/config/profiles/save` 接收 `ProfileSaveRequest`；`POST /api/config/profiles/{profile_id}/activate` 接收 `{expected_revision}`；`POST /api/config/probe-draft` 接收 `ProbeRequest`。保存和激活返回 `ProfileView`。不新增方案删除、版本浏览、回收站功能，避免把尚未确定的建议扩成需求。

00数据库接入申请：新增 `config_profiles(profile_id PK, name, payload_json)`、`config_credentials(credential_id PK, provider, base_url, secret)`、单行 `config_profile_state(id PK CHECK(id=1), active_profile_id, revision, legacy_migrated)`。方案 JSON 只含凭据引用；数据库属于服务端持久目录，沿用部署访问权限，不宣称已做加密。DDL必须纳入既有版本/校验和迁移，不修改已应用版本的校验内容。没有迁移门禁通过时，本包只运行独立临时数据库测试，不另建生产表绕过迁移。

凭据按地址和服务绑定；新密钥保存为新凭据记录，避免修改一套方案时暗改其他方案。另存为可复用同一凭据引用。服务地址变化不得带出旧密钥；无新密钥返回 `LLM_KEY_REQUIRED`。`expected_revision` 不匹配返回409 `CONFIG_REVISION_CONFLICT`，不静默覆盖。保留环境变量覆盖保护：被部署环境锁定的项显示只读，尝试覆盖返回409 `CONFIG_ENV_OVERRIDE`。

跨包依赖与输出：

- 00/集成包先提供数据库迁移、公共 TypeScript 类型、方案初始化调用及管理端兼容接入；本包实现专属仓库与模型，不直接改公共文件。
- 搜索包提供其冻结的状态/测试 API；本包只保存 `search` 凭据引用并在配置页消费。不在模型 `ProbeReport.passed` 中混入搜索结果，申请链接由搜索包给出经核对的服务商地址。
- 选题包将 `backend/app/api/endpoints/topic.py` 普通聊天改为 `chat(messages, role='topic')`；清洗/图表/章节包分别传 `data`/`chart`/`writer` 等明确角色。
- 集成包将向导全局 `configStatus === ready` 门禁改为当前动作所需角色检查；开始写作与上传资料不要求八角色全齐。统一测试则检查全部八角色，语义不能混用。
- 资料包移除基本阅读对 `get_embeddings_client()` 的依赖；本包只令可选向量调用缺能力时返回 `EMBEDDING_NOT_CONFIGURED`，不伪造向量、不扩展套餐能力。

## 3. Task 1：命名方案原子保存、恢复与旧配置迁移

**Files:** 新增 `models/config_profiles.py`、`repositories/config_profile_repository.py`、`backend/tests/test_config_profiles.py`；修改 `core/config.py`、`api/endpoints/config.py`。路径前缀均为 `backend/app/`，测试路径除外。

**Interfaces:** 输入00冻结的表结构和上述保存契约；输出 `save_and_activate`、`activate`、`active_snapshot`、方案HTTP接口。后续任务只读取快照，不能直接解析 `.env` 或复制凭据。

- [ ] 写下列接口回归，先运行并确认因路由/持久模型缺失而失败；`client` 使用已有隔离设置和存储fixture。

```python
def test_profile_reopen_and_no_secret_echo(client):
    revision = client.get('/api/config/profiles').json()['config_revision']
    first = client.post('/api/config/profiles/save', json={
        'expected_revision': revision,
        'draft': {'name': '仅角色方案', 'default_model': None,
                  'services': [{'service_id': 'plan-a', 'provider': 'glm_coding',
                                'base_url': 'https://example.com/v1', 'api_key': 'test-secret'}],
                  'roles': {'topic': {'service_id': 'plan-a', 'model': 'test-model'}}}})
    assert first.status_code == 200
    assert 'test-secret' not in first.text
    saved = first.json()
    listing = client.get('/api/config/profiles').json()
    assert listing['active_profile_id'] == saved['profile_id']
    reopened = next(p for p in listing['profiles'] if p['profile_id'] == saved['profile_id'])
    assert reopened['draft']['default_model'] is None
    stale = client.post('/api/config/profiles/save', json={
        'expected_revision': revision, 'draft': {'name': '冲突方案'}})
    assert stale.status_code == 409
    assert client.get('/api/config/profiles').json()['active_profile_id'] == saved['profile_id']
```

- [ ] 实现同事务流程：验证名称非空、角色已知、服务ID不重复和引用完整 → 检查修订号 → 建凭据记录 → 写无密钥方案JSON → 设置活跃ID并递增全局revision → 提交。任何一步异常全部回滚；提交后清客户端缓存。不能因角色未填齐阻止保存草稿方案。
- [ ] 实现 `migrate_legacy`：`legacy_migrated` 未置位时，将默认服务、本地模式、`ROLE_MODELS`、`PROVIDER_CREDENTIALS`、Tavily配置生成“现有配置”方案，同事务置位；重复启动不重复创建。无法解析旧JSON时报告 `CONFIG_MIGRATION_INVALID` 和字段名，保留原文件；不把错误映射为“全部跟随默认”。
- [ ] 让活动配置以数据库事务为事实来源；`get_settings()` 的既有非模型部署设置继续来自环境，模型相关兼容视图来自活动快照。禁止同时写数据库和 `.env` 构成半成功状态。`update_settings()` 中遗留模型变更委托仓库事务，非模型部署项沿用原文件写法；包含两种类别的遗留写入经集成门禁选用单一协调入口，不自行做无事务双写。
- [ ] 扩展测试：关闭并重建 TestClient 后恢复活跃方案；中途写凭据异常无残留；重复迁移只一套；空密钥保留；地址变化不复用；读响应、错误、日志均无密钥；环境锁定不可覆盖。保留旧 `/config/`、`/update` 兼容行为，混合管理端更新由集成包接入后回归，未通过不得宣称迁移完成。

**Run:** `python -m pytest backend/tests/test_config_profiles.py backend/tests/test_config_update.py -q`。预期所有离线断言通过，数据库和 `.env` 均使用测试隔离目录。任务验收是保存/切换/重启/冲突真实持久化通过，不是页面显示“保存成功”。

## 4. Task 2：可选默认模型与按角色解析

**Files:** 修改 `backend/app/services/model_roles.py`、`backend/app/core/clients.py`；新增 `backend/tests/test_config_role_capabilities.py`。

**Interfaces:** 消费 Task 1 的 `RuntimeSnapshot`；输出上述 `resolve_role_target` 和 `check_capabilities`。旧 `role=None` 仍表示显式请求默认模型，不准任取第一个角色模型补位。

- [ ] 写不依赖默认模型的单测，确认旧实现失败。

```python
def test_explicit_role_without_default():
    from backend.app.models.config_profiles import ConfigDraft, RuntimeSnapshot
    from backend.app.services.model_roles import check_capabilities, resolve_role_target
    snap = RuntimeSnapshot(config_revision=7, draft=ConfigDraft.model_validate({
        'name': '套餐', 'default_model': None,
        'services': [{'service_id': 'p', 'provider': 'glm_coding',
                      'base_url': 'https://example.com/v1', 'api_key': 'offline'}],
        'roles': {'topic': {'service_id': 'p', 'model': 'm'}}}))
    assert resolve_role_target('topic', snapshot=snap).model == 'm'
    assert check_capabilities(['topic'], snapshot=snap) == []
    issues = check_capabilities(['writer'], snapshot=snap)
    assert [(i.role, i.code) for i in issues] == [('writer', 'ROLE_MODEL_MISSING')]
```

- [ ] 按“显式角色绑定 → 空绑定跟随默认 → 报具体缺项”解析；本地模型只影响绑定到该服务的角色，不能由全局开关覆盖其他角色。未知角色返回 `ROLE_MODEL_INVALID`；缺服务/模型/密钥分别返回 `ROLE_SERVICE_MISSING`、`ROLE_MODEL_MISSING`、`ROLE_MODEL_KEY_MISSING`，详情包括角色和服务ID。
- [ ] 保留 `ModelTarget(provider, base_url, model, api_key)` 既有使用，扩展字段提供默认值；`check_capabilities` 收集所有指定角色的错误，不遇第一项便停止。`describe_target` 复用同一解析结果；单次请求只捕获一次快照。`RuntimeSnapshot` 采用冻结模型并深拷贝嵌套草稿，内部不暴露可写集合，防止请求途中被页面保存或其他调用修改。
- [ ] 向量客户端单独检查其现有向量设置和凭据；缺项返回 `EMBEDDING_NOT_CONFIGURED`。不以聊天套餐“可用”推出支持embedding；不在 `check_capabilities(['topic'])` 中验证向量能力。
- [ ] 补测默认存在时八角色回退、显式角色优先、本地与远程混用、无默认的 `role=None`、未知角色、快照切换不串密钥。向集成包提交调用入口清单，附 `topic.py` 无角色调用修正请求；本包不修改该文件。

**Run:** `python -m pytest backend/tests/test_config_role_capabilities.py backend/tests/test_multi_model.py -q`。旧跨模块断言若因已确认需求变化失效，交由所属包调整；不删测试掩盖缺默认模型回归。

## 5. Task 3：真实最小调用、协议适配与计费一致

**Files:** 修改 `backend/app/core/clients.py`、`backend/app/core/llm_gateway.py`、`backend/app/services/model_providers.py`；在 `backend/tests/test_config_draft_probe.py` 增加传输和计费测试。

**Interfaces:** 输入 `ModelTarget`；输出 `probe_target(target)`。内部抽取 `invoke_target(messages, target, *, probe: bool) -> str` 供 `chat` 和探测复用；它不是给其他包绕过角色检查的公共API。

- [ ] 写传输层测试，模拟同服务 `/models` 返回200、生成接口返回403，断言探测失败；本地 `/api/tags` 返回模型但生成请求失败，同样不得通过。使用 `httpx.MockTransport` 或现有客户端工厂替身，禁止联网。
- [ ] 将协议能力明确分为现有 OpenAI 兼容、Ollama 兼容生成及不支持的原生协议。`get_chat_client_for` 增加有默认值的 `api_style` 和 `max_output_tokens` 关键字参数，并纳入缓存键。目录存在但尚无可验证适配器时返回 `MODEL_PROTOCOL_UNSUPPORTED`，不能在原生 Anthropic 地址发 `/chat/completions` 后称兼容完成。新增原生SDK不在本包范围；确需接入先提交00依赖申请及官方协议证据。
- [ ] 使用短提示“Reply OK”真实生成，输出预算沿用协议可接受的最小有限值；不统一硬写所有服务 `max_tokens=1`。默认建议32 token，由适配器处理参数名称与限制；套餐拒绝此上限时返回明确参数错误，核对官方接口后调整，不把错误自动当成功。保留超时，关闭隐式重试，避免不透明重复费用。
- [ ] 抽取共用调用边界：先隐私处理、`reserve`、`mark_dispatched`、实际请求、`settle`；已发请求无usage时保留未知消耗机制，失败也结算未知状态；协议/地址/缺密钥等请求前失败不产生已发请求记录。继续使用现有安全出站客户端，不绕过私网/DNS限制。
- [ ] 归一化401/403、404模型不存在、429限额、超时、无效响应、协议不支持等错误，输出安全错误码和短原因，不回显原始响应头/密钥。补测每次探测只预留/派发/结算一次、模型清单请求不冒充生成请求、缓存不会跨密钥或输出上限复用。

示例测试结构（放在同一专属测试文件，直接构造既有 `ModelTarget`，不依赖未定义fixture）：

```python
def test_probe_uses_same_accounted_path(monkeypatch):
    import asyncio
    from backend.app.core import llm_gateway
    from backend.app.services.model_roles import ModelTarget
    seen = []
    async def fake_invoke(messages, target, *, probe):
        seen.append((target.model, probe, messages[-1]['content']))
        return 'OK'
    monkeypatch.setattr(llm_gateway, 'invoke_target', fake_invoke)
    result = asyncio.run(llm_gateway.probe_target(ModelTarget(
        provider='custom', base_url='https://example.com/v1', model='m', api_key='offline')))
    assert seen == [('m', True, 'Reply OK')]
    assert isinstance(result['latency_ms'], int)
```

**Run:** `python -m pytest backend/tests/test_config_draft_probe.py backend/tests/test_usage_lifecycle.py backend/tests/test_security.py -q`。上述结构测试必须与真实传输替身和计费断言一起通过，单纯mock整条调用不能证明协议可用。

## 6. Task 4：基于草稿的全角色统一验证

**Files:** 修改 `backend/app/api/endpoints/config.py`、`frontend/src/api/config.ts`；扩展 `backend/tests/test_config_draft_probe.py`。

**Interfaces:** 消费 Task 1 草稿解密解析和 Task 3 `probe_target`；输出 `ProbeReport`，不改变保存方案。前端封装 `probeDraft(input: ProbeRequest): Promise<ProbeReport>`，公共类型由00提供。

- [ ] 编写统一测试失败用例：八角色同一绑定、无默认，仅一次生成请求；有默认且相同目标仍一次；一个角色缺失、七个可用时整体失败但其他结果完整；相同模型不同凭据/地址不可合并。
- [ ] 实现一次草稿解析，固定排序遍历八角色，另在默认非空时加入 `default` 行；空角色按默认解析，无默认则返回 `missing`。按规范化地址、凭据指纹、模型及实际协议去重；指纹仅内部使用，不写日志或响应。每个独特目标探测一次，结果映射到所有引用它的行。
- [ ] 对单个目标的 `AppException` 捕获为失败行，继续其余目标；整体 `passed` 仅在全部八角色且可选默认的结果均为 `passed` 时成立。方案名、服务地址、模型、角色或密钥变化均令前端旧结果失效。服务端凭据版本冲突返回409，避免测试误用已被其他窗口替换的密钥。
- [ ] 请求返回原样的 `draft_version` 和使用的 `config_revision`。测试不保存任何草稿或新凭据；错误时也不能变更活跃方案或修订号。旧单模型测试路由保留给兼容调用方但不能驱动新页面整体通过状态。
- [ ] 用下面的完整草稿结构做mock端到端断言，并增加403、超时、缺角色、凭据不一致、不保存的断言。

```python
def test_dedup_maps_all_roles_without_persisting(client, monkeypatch):
    from backend.app.api.endpoints import config as endpoint
    from backend.app.services.model_roles import VALID_ROLES
    calls = []
    async def fake_probe(target):
        calls.append(target.model)
        return {'latency_ms': 1, 'message': '调用成功'}
    monkeypatch.setattr(endpoint, 'probe_target', fake_probe)
    before = client.get('/api/config/profiles').json()
    reply = client.post('/api/config/probe-draft', json={
        'draft_version': 9, 'expected_revision': before['config_revision'],
        'draft': {'name': '未保存', 'default_model': None,
                  'services': [{'service_id': 'p', 'provider': 'custom',
                                'base_url': 'https://example.com/v1', 'api_key': 'offline'}],
                  'roles': {role: {'service_id': 'p', 'model': 'm'} for role in VALID_ROLES}}})
    assert reply.status_code == 200
    report = reply.json()
    assert report['passed'] is True and report['draft_version'] == 9
    assert {row['role'] for row in report['rows']} == VALID_ROLES
    assert calls == ['m']
    assert client.get('/api/config/profiles').json() == before
```

**Run:** `python -m pytest backend/tests/test_config_draft_probe.py -q`。真实服务验证另见Task 5，离线通过不写成套餐已实测可用。

## 7. Task 5：统一配置草稿、切换保护与交付验证

**Files:** 修改 `frontend/src/pages/ConfigPage.tsx`、`frontend/src/api/config.ts`；新增 `frontend/src/test/configProfiles.test.tsx`。公共状态和类型变更由集成包提供。

**Interfaces:** 消费方案列表/保存/激活/草稿测试；搜索状态和验证消费搜索包冻结契约。页面不承担搜索实现，不用模型成功推断搜索成功。

- [ ] 编写组件交互测试：修改角色后点击统一“保存配置”，请求同时包含主模型、角色、服务和搜索关联；保存成功才解除dirty状态。删除原有分区“保存凭据”“保存分工”入口，允许默认模型为空，不保留强制主Key校验。
- [ ] 实现“当前方案／已保存／未保存变更”状态、命名另存为和方案选择。切换有草稿时提供“保存后切换／放弃变更后切换／取消”；保存失败或409时停留原草稿，不能清空密钥输入或假装切换成功。刷新前使用浏览器离开提醒，密钥不落localStorage、IndexedDB或日志。
- [ ] 维护单调递增版本ref；每次字段编辑、方案切换和新测试开始递增，完成时只有响应版本等于当前版本才能显示。下面的比较逻辑放在页面请求完成回调，测试需延迟旧请求并验证页面不显示旧通过结果。

```typescript
const requestVersion = ++draftVersionRef.current
const report = await probeDraft({
  draft: currentDraft,
  draft_version: requestVersion,
  expected_revision: configRevision,
})
if (report.draft_version !== draftVersionRef.current) return
setProbeReport(report)
```

- [ ] 底部只保留统一模型“测试连接”，注明“将向当前已选模型发起真实请求，可能产生少量消耗”。表格逐角色展示服务、模型、结果和失败原因；新编辑立即清除旧“通过”标识。列表加载只表示列表可读取，角色旁现有列表获取行为不升级成强制刷新时间功能。
- [ ] 接入搜索包提供的申请入口、未配置/失败/无匹配/成功等状态及独立真实搜索验证；搜索控件与模型结果分区显示，搜索失败不能写成模型失败或“已完成检索”。密钥说明统一为“保存在当前部署的服务端，不在页面回显”；部署模式由实际配置说明，不猜测用户设备位置。
- [ ] 执行组件/构建/后端回归，交由集成包验证仅角色配置能进入相应业务动作、资料上传不要求模型/向量齐全。使用现有页面上下文mock，独立测试文件不得修改全局fixture或向导实现。

**Run（项目根目录）:**

```powershell
python -m pytest backend/tests/test_config_profiles.py backend/tests/test_config_role_capabilities.py backend/tests/test_config_draft_probe.py backend/tests/test_config_update.py backend/tests/test_multi_model.py backend/tests/test_model_providers.py backend/tests/test_config_review_integration.py -q
npm --prefix frontend test -- src/test/configProfiles.test.tsx
npm --prefix frontend run build
```

真实环境验收单独执行，不能移除 `backend/tests/conftest.py` 的禁网保护：启动已配置的应用，在配置页仅给角色绑定用户实际套餐模型，默认留空；先拉取清单，再点击底部统一测试；记录角色、服务、模型、错误码、是否真实派发及消耗说明，不记录密钥。分别验证一套实际可用套餐、无调用权限模型、本地生成（环境具备时）及切换后旧结果失效。未提供密钥或本地服务未安装的场景记为“未执行及原因”，不以mock通过替代。包交付可以提交离线代码验收，但整个产品的“真实连接已通过”声明必须等对应真实请求成功后才能给出。

## 8. 迁移、失败处理和最终交付门禁

- 数据库新增版本由00统一安排；启动迁移幂等，旧文件保留用于回滚。回滚前恢复旧软件及对应数据库备份，不能用旧程序写入较新schema。
- 管理端配置、应用配置页和运行时必须看到同一活动方案修订；旧管理端含部署项的混合更新须由集成包完成协调后验收，不能只测新页面。
- 保存事务失败保留旧活动方案；测试失败不保存；激活失败保留页面草稿；预算拒绝是明确失败行，不显示连接成功。
- 八角色整体测试通过只证明当次草稿的最小生成请求通过，不证明长上下文、视觉或向量能力均可用。
- 同一文件不安排多个agent同时实现。Task 1先行；Task 2完成后Task 3；Task 4依赖1—3；Task 5可先写独立页面测试，最终接入依赖4及搜索契约。与资料、选题、数据、图表等包可在00冻结后并行。

交付时逐项附证据：

- [ ] 专属文件差异及与00冻结契约的对照；没有越界改公共文件。
- [ ] 新旧配置迁移、重启、修订冲突、错误回滚和密钥不回显测试记录。
- [ ] 无默认模型的角色调用与八角色草稿去重测试记录。
- [ ] 真实请求路径、计费结算和出站保护回归记录。
- [ ] 配置页统一保存、脏草稿保护、乱序结果失效和独立搜索结果记录。
- [ ] 各业务调用入口的明确role核对表；选题无角色调用由所属包修复并由集成包验收。
- [ ] 真实服务测试已执行/未执行清单及原因；不得把目录收录、模型列表成功或mock成功写成真实套餐可用。
