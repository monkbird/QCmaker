# QCmaker 管理后台（Admin Console）建设规划 v2

> 版本：v2.0
> 文档状态：用户已批准预览并授权实施，本地开发与验收已完成。本文不表示生产部署已经完成。
> 编制依据：现有 backend/app、frontend/src、docs/admin-console-plan-review.md，以及 docs/admin-console-preview/ 玻璃后台预览。
> 交付原则：每项能力均按“使用场景 → 数据来源与真实模型 → 权限 → 前置状态 → 请求与响应 → 事务/并发/重试 → 页面反馈 → 审计 → 验收”编写。

---

## 一、规划背景与目标

### 1.1 背景

当前 QCmaker 采用单团队共享令牌模式。业务接口主要使用 API_ACCESS_TOKEN，系统已有数据集、研讨会话、用量账本、生成成果、日志和 Chroma 知识库，但缺少独立的管理员身份、运营视图和受控运维入口。现有业务配置接口和预算复位入口仍可能由业务令牌调用，因此“管理认证独立”不能直接等同于“所有敏感能力已经从业务入口隔离”。

### 1.2 建设目标

| 目标 | 可交付结果 |
|---|---|
| 运营可视 | 总览、用量成本、预算预留、会话、成果、知识库、系统状态和运营事件流 |
| 操作可控 | 数据集、会话、PPT 成果、项目知识库、预算、配置和维护任务具备明确范围、确认、并发和失败处理 |
| 管理可追溯 | 管理写操作在权限校验、审计写入、业务写入之间形成闭环，含 actor、request_id、operation_id、结果和安全摘要 |
| 业务兼容 | 继续支持既有业务令牌和向导流程；管理路由独立关闭，未初始化时不影响业务路由 |
| 可回滚 | 有 schema 版本、旧库升级、WAL 备份、配置回滚、外部文件/向量对账和在途任务恢复方案 |

“全程可审计”在本方案中专指管理接口操作。遗留业务敏感入口继续兼容时，不承诺这些入口全部自动形成管理员审计；如以后要求全系统统一审计，须另行改造共享服务层或迁移业务鉴权。

### 1.3 本期范围

- 单管理员账号模型，保留 admin_users 多行结构，为后续多人和角色扩展预留字段；
- 独立管理员 Cookie 会话、会话吊销、CSRF、防暴力和来源限制；
- 总览、用量与预算、数据集、研讨会话、PPT 成果、项目知识库、日志、系统状态、安全中心、配置和审计查询；
- 管理写操作的数据库事务审计、文件/Chroma 操作意图和补偿；
- 同源浏览器部署、响应脱敏、分页、CSV 导出、迁移回滚和浏览器端到端验收。

### 1.4 非目标

- 多租户、多组织和完整 RBAC；
- 上传文件生命周期管理。本期 files 表只代表已生成 PPT 成果登记；若新增通用上传，须另立上传持久化和登记设计；
- 物理 Chroma collection 的删除管理。页面以项目知识库为单位，物理集合仅作只读运维信息；
- 已物理删除数据的在线“恢复”。恢复数据需依赖备份/回收站方案，不能把软件回滚当作数据恢复；
- PDF 报表默认交付。PDF 作为独立可选能力，需另行确定转换器、部署依赖和版式验收；
- 当前交付阶段不执行生产实现或上线；用户确认预览并决定实施后，再按本方案实施业务代码改动。

### 1.5 视觉与预览约束

管理后台沿用 docs/admin-console-preview/ 中的 Dribbble 风格液态玻璃方向，预览通过后才进入生产实施。设计约束如下：

- 去掉顶栏左侧的三色点，不使用模拟窗口控制点代替真实导航；
- 顶栏与侧栏首层控制条高度统一为 48px，图标、文字和焦点态按该基准对齐；
- 加强整体阴影层次，使卡片、浮层和主框架在玻璃背景上保持清晰边界；阴影不能替代文字和控件对比度；
- 延续现有 liquid-glass token、Ant Design 组件和 ECharts；桌面、平板、390px 移动宽度均要有空态、加载态、错误态和键盘焦点态；
- 任何视觉调整均不得让管理路由初始化向导状态或触发业务接口请求。

V01、V02、V03 的逐项基线和截图见 docs/admin-console-preview/design-spec.md；正式实现以前端预览和该设计规格共同验收。

---

## 二、现状盘点与能力边界

### 2.1 可复用能力与真实模型

| 能力 | 现状位置/模型 | v2 复用与修订 |
|---|---|---|
| 用量和预算 | services/usage.py 的 usage_events、reservations、get_usage | 查询保留账本精度；unknown 和 provider_overrun 不当作可释放余额 |
| 过量复位 | reset_provider_overrun | 保留业务入口兼容；管理入口增加近期密码确认、审计和 operation_id |
| 清理任务 | services/maintenance.py、usage.py、ppt.py | 拆出带 scope 的清理服务，定时与手动共享互斥/去重 |
| 数据集 | datasets，含 raw_rows_json、current_rows_json、report_json | 管理响应只出允许字段；删除范围不扩展到会话快照、向量或成果 |
| 会话 | discussion_sessions、discussion_commands、discussion_events | 沿用 finished 终态；增加管理取消终态 cancelled，维护租约 generation |
| PPT 成果 | services/ppt.py 将生成结果登记到 files，文件位于 generated_ppts | files 是成果登记源；目录扫描只作孤儿/缺失/临时文件核对 |
| RAG | services/rag.py 按 embedding 指纹生成物理集合，project_id 在 metadata 中 | 项目与 collection 分离；跨所有相关集合按 project_id 过滤 |
| 日志 | backend/logs/app.log 及 RotatingFileHandler | 只允许服务端固定目录，游标包含文件身份和字节位置 |
| 配置 | core/config.py、既有 config endpoint | 先校验候选配置，再原子写入；expected_revision 防覆盖，环境变量覆盖项只读 |
| 鉴权/安全头 | core/security.py、main.py 中的中间件 | 管理流量单独分类；浏览器生产和开发均以同源代理为前提 |

### 2.2 管理与业务能力矩阵

| 能力 | 管理接口 | 遗留业务接口 | 审计承诺 |
|---|---|---|---|
| 管理账号、会话、审计查询 | 管理会话 + CSRF | 不开放 | 管理接口完整审计 |
| 数据集查看/删除/过期清理 | 管理会话 + CSRF | 业务流程继续使用原接口 | 管理操作完整审计；业务流程不自动归入管理员审计 |
| 会话恢复/取消 | 管理会话 + CSRF | WebSocket 继续按业务令牌工作 | 管理操作完整审计；旧业务连接按既有协议处理 |
| PPT 下载/删除 | 管理下载包装器/管理写接口 | 既有下载接口继续要求业务凭证 | 管理操作完整审计；业务下载不承诺管理员审计 |
| 项目文档查看/删除 | 管理 metadata 路径，不初始化 embedding client | RAG 业务接口继续使用业务凭证 | 管理操作完整审计 |
| 配置更新/预算复位 | 管理接口 | 既有 config.py 入口暂保兼容 | 管理接口完整审计；遗留入口不承诺全系统审计 |
| API_ACCESS_TOKEN 轮换 | 管理接口，近期密码确认 | 业务调用方需重新配置 | 管理轮换完整审计 |

当前 verify_access_token 在 API_ACCESS_TOKEN 未配置时直接放行，本身不校验来源是否回环。因此，无业务令牌模式必须由监听地址及网络边界限制为受信任本机访问；一旦网络共享部署，必须配置业务令牌，不能仅因前置代理在本机就允许匿名远程请求。

---

## 三、总体架构

### 3.1 运行边界

~~~text
React SPA
  ├─ 业务路由 /config /topic /data /discussion /visualization /ppt
  │    └─ x-api-token
  └─ 管理路由 /admin/*
       └─ 同源 Cookie + X-CSRF-Token
              │
              ▼
FastAPI 单进程
  ├─ 业务 API：既有 verify_access_token
  ├─ 管理 API：verify_admin、来源校验、CSRF、管理限流
  ├─ 共享服务：usage / maintenance / ppt / rag / discussion_session
  └─ 管理服务：admin_security / audit / operations / admin_metrics
              │
              ├─ SQLite WAL：业务表、管理表、审计、操作意图
              ├─ ChromaDB：按物理集合保存、按 metadata.project_id 隔离
              └─ 固定目录：generated_ppts、logs、data
~~~

生产和开发均使用同源代理：浏览器访问同一站点的 /admin 和 /api/admin，开发环境由前端代理转发，生产环境由反向代理将 /admin/* 刷新回退到 SPA、将 /api/* 转发到 FastAPI。v2 不依赖跨源 Cookie；若未来采用跨源部署，须另行明确精确 Origin 白名单、allow_credentials 和预检策略后才能上线。

### 3.2 关键决策

| 决策 | 规则 |
|---|---|
| 凭证来源 | 环境变量只负责首次 bootstrap；首次成功写入后 admin_users 是唯一权威，启动不得用环境变量覆盖数据库密码或用户名 |
| 管理开关 | ADMIN_ENABLED 是独立开关；关闭返回 503 ADMIN_DISABLED，不根据是否有密码字段隐式启用 |
| CSRF | 登录使用严格 Origin + application/json；登录/me 响应返回会话绑定 token，前端只存内存并回填请求头，不使用可读 CSRF Cookie |
| 会话寿命 | 用户交互空闲 30 分钟失效；自动轮询不续期；绝对寿命 8 小时，服务端最终裁决 |
| 改密 | 验证旧密码和新密码策略；成功后吊销全部会话（含当前）、清 Cookie，必须重新登录 |
| 审计 | 数据库敏感写操作与审计同事务；文件/Chroma/配置写入先保存 operation intent，再执行并补偿/对账 |
| 研讨终态 | finished 和 cancelled；不使用 ended。租约依靠 owner、generation、lease_until，恢复递增 generation |
| 文件 | files 仅作为 PPT 成果登记源；不把目录扫描结果当作可下载记录 |
| 项目知识库 | project_id 是业务隔离键，不是 collection 名；跨集合过滤和删除不依赖 LLM/embedding 凭证 |
| 令牌轮换 | 新 HTTP 请求和新 WS 连接拒绝旧令牌；已连接 WS 保持到关闭前，前端需更新构建/部署配置后重新接入 |
| 环境覆盖 | 进程环境变量优先于 .env；管理页展示来源并拒绝写入被覆盖字段 |

---

## 四、领域定义与安全模型

### 4.1 管理员初始化、禁用与本机恢复

配置项采用以下语义：

~~~dotenv
ADMIN_ENABLED=false
ADMIN_BOOTSTRAP_USERNAME=
ADMIN_BOOTSTRAP_PASSWORD_HASH=
ADMIN_SESSION_IDLE_MINUTES=30
ADMIN_SESSION_ABSOLUTE_HOURS=8
ADMIN_LOGIN_RATE_PER_MINUTE=5
ADMIN_ALLOWED_IPS=
ADMIN_CSRF_TOKEN_TTL_MINUTES=120
ADMIN_MAX_SESSIONS=20
~~~

- ADMIN_ENABLED=false 时，所有 /api/admin/* 均返回 503 ADMIN_DISABLED；前端展示关闭说明，业务路由继续工作。
- ADMIN_ENABLED=true 且 admin_users 为空时，启动或首次管理请求执行一次 bootstrap。用户名和哈希必须同时存在；bootstrap 校验用户名、哈希格式、算法、盐长度及迭代数，明文密码长度由生成哈希的本机工具校验（服务端不能从哈希反推明文长度）；缺任一项返回 503 ADMIN_NOT_INITIALIZED，不创建半成品账号。
- admin_users 已有有效账号后，ADMIN_BOOTSTRAP_USERNAME 和 ADMIN_BOOTSTRAP_PASSWORD_HASH 只作为历史配置记录，不参与登录，不覆盖数据库，也不因重启回滚页面改密。
- 数据库已有账号而 bootstrap 环境变量缺失时，继续使用数据库账号；数据库不可读、迁移失败或账号不存在时不回退到环境变量，返回明确 503 并保留业务服务。
- 改用户名本期不开放；如需改变，采用本机恢复流程或未来独立迁移，避免用环境变量悄然替换数据库身份。
- 本机恢复是一次性本地运维命令/受控主机流程，不提供远程 HTTP 重置接口；流程验证本机权限，设置新密码、必要时启用 ADMIN_ENABLED、吊销全部会话，并以 local-recovery 身份写入审计/运营记录。
- 密码策略为至少 12 个字符，采用 PBKDF2-HMAC-SHA256、至少 600000 次迭代和随机盐；无效哈希在 bootstrap 时拒绝，登录失败不泄露账号存在性。
- admin_users 的 is_active=false 时拒绝登录；禁用和恢复均需明确的本机或管理操作记录。
- CSRF 签名密钥由服务端生成并保存在受保护的本机数据目录，不作为管理员密码来源；密钥丢失或主动轮换时吊销现有管理会话后重新生成，避免重启后无法重算 token。

### 4.2 Cookie、Origin 与 CSRF

- 登录请求必须是同源 Origin，Origin 与受信代理计算出的站点 Origin 精确匹配，且 Content-Type 为 application/json；不接受表单、JSONP 或缺失/不匹配 Origin 的跨站登录。
- 登录是预会话接口，免除业务 CSRF 头，但必须经过独立登录限流、来源检查、JSON schema 和密码校验。登录失败只返回统一 401/429 文案。
- 登录成功生成随机 session secret，数据库只存 SHA-256 token_hash；设置 qc_admin_sid：HttpOnly、SameSite=Strict、Path=/api/admin、host-only Domain、生产 HTTPS 下 Secure、Max-Age 不超过 8 小时。仅在显式 development 模式、浏览器 Origin 为 localhost/127.0.0.1 且后端绑定回环地址时允许本地 HTTP Cookie 省略 Secure；其他部署缺少 HTTPS 时拒绝启用管理登录。
- 登录/me JSON 同步返回 csrf_token、server_time、idle_expires_at、absolute_expires_at。csrf_token 由服务端稳定的 CSRF 签名密钥、固定用途字符串、session_id、csrf_generation、csrf_token_created_at 和本次请求中的原始 sid 通过 HMAC-SHA256 派生；数据库保存 csrf_token_created_at、csrf_generation、csrf_key_version，服务端可在 me 中重算，不能只存一个无法还原明文 token 的 hash；前端只把明文 token 放入当前标签页内存，刷新页面后通过 me 重新读取。
- 所有管理 POST、PUT、PATCH、DELETE（登录除外）必须同时具备有效会话和 X-CSRF-Token；服务端先用原始 sid 的 SHA-256 查找会话，再按 session_id、sid、csrf_generation、csrf_token_created_at 和 csrf_key_version 重算期望 token，以常量时间比较请求头、token TTL 和 revoked_at，不能只比较两个客户端字符串。
- 同一会话重复 Cookie、重复 CSRF 头、跨会话 token、过期 token、错误 Path 清 Cookie 均是拒绝/清理测试项。csrf_token 过期时返回 403 ADMIN_CSRF_EXPIRED，前端调用 me 获取新 token；me 在 token 过期时通过事务 CAS 递增 csrf_generation 并更新创建时间，再返回派生新值，未过期时只返回现值。旧 generation 的 token 始终拒绝；多标签页通过一次 me 同步，不无限自动重试写请求。会话过期则跳转登录。
- logout 需要 CSRF 时吊销当前会话并清除 Cookie；已过期或已吊销的 logout 可返回稳定成功结构，不能借此恢复会话。清 Cookie 必须复用 HttpOnly、Secure、SameSite、Path 和 host-only 属性。
- 管理响应统一 Cache-Control: no-store、Pragma: no-cache；会话和配置响应不允许浏览器、代理或 Service Worker 缓存。

### 4.3 会话空闲、绝对寿命与多标签页

admin_sessions 至少保存 created_at、last_activity_at、last_request_at、idle_expires_at、absolute_expires_at 和 revoked_at。用户活动与请求活动分开：

- 由点击、提交、筛选、分页、下载等真实交互触发的请求带 X-Admin-User-Activity: 1，服务端在事务内更新 last_activity_at；
- 看板轮询、日志尾随、后台标签页刷新、AdminGuard 的静默 me 检查不带该标记，不延长空闲期限；
- 前端可以在用户交互后节流调用 POST /auth/activity，但该请求也必须 CSRF，且服务端仍检查绝对截止时间；
- 任何请求都不能把 absolute_expires_at 向后移动；30 分钟从最近一次用户活动计算，8 小时从登录计算；
- 前端倒计时以 server_time 和服务端截止时间为准，后台标签页恢复时立即重新 me；多个标签共享 Cookie，但每个标签的内存 CSRF token 需在 403/刷新后同步；
- 服务端超过 idle_expires_at 或 absolute_expires_at 直接 401 ADMIN_SESSION_EXPIRED，轮询不能“保活”；
- admin_sessions 过期/吊销记录由维护任务定期清理，保留最近审计所需的摘要；达到 ADMIN_MAX_SESSIONS 时拒绝新登录并返回 409 ADMIN_SESSION_LIMIT，提示先吊销旧会话；不静默踢出任何现有会话。过期或已吊销会话不计入上限。

### 4.4 限流、来源白名单和关闭优先级

- /api/admin/auth/login 在 RateLimitMiddleware 之前完成路由分类，使用独立的 IP 窗口；不扣业务 API 额度。管理已认证读写可使用独立管理限额，OPTIONS 不计入额度。
- 默认登录限流为每 IP 每分钟 5 次；连续失败 10 次锁定 15 分钟。失败计数按规范化账号与可信来源 IP 组合记录，同时保留 IP 级总量，成功登录清零对应计数；未知账号与已存在账号返回同一错误。
- 可信来源 IP：未配置代理时读取 socket peer；仅当部署明确声明代理可信时才解析 X-Forwarded-For 的指定位置。ADMIN_ALLOWED_IPS 用逗号分隔的 IPv4/IPv6/CIDR，经 ipaddress 解析，格式错误启动即失败。
- 高成本密码校验使用进程内并发信号量并设置等待上限；限流和锁定记录落库，重启不会清零。锁定自动到期；提前解锁只走本机恢复流程。
- ADMIN_ENABLED=false 或管理员未初始化时，优先返回 503，不泄露登录账号状态，也不被全局业务额度吞掉。限流返回 429 和 Retry-After；IP 不允许返回 403 ADMIN_IP_DENIED。

### 4.5 审计、操作意图与事件流

管理写操作先生成 request_id 和 operation_id。数据库内操作在同一个 BEGIN IMMEDIATE 事务中完成业务变更和 audit_logs 插入；审计插入失败则整体回滚并返回 503 AUDIT_UNAVAILABLE，不能继续执行后再“尽力记日志”。

文件删除、Chroma 删除、.env 替换和跨存储维护采用以下顺序：

1. 在数据库事务中校验权限、scope、expected_revision/幂等键，写入 admin_operations 的意图、目标安全摘要和 audit_logs 的 REQUESTED 记录；
2. 提交后执行文件/Chroma/配置外部动作，逐项记录成功、失败、跳过和部分完成；
3. 以新的事务写最终状态和 SUCCEEDED、PARTIAL 或 FAILED 审计记录；失败进入可查询重试队列；
4. 启动维护和手动维护扫描 pending/running 操作，按幂等规则恢复或标记需要人工对账。

operation_events 是看板动态流和告警展示，不替代敏感操作审计。非关键运营事件写入失败可降级到结构化日志，但不能影响已经完成的核心业务写。事件生产者包括登录安全、配置/令牌、预算熔断、维护、会话状态、PPT、RAG 操作和依赖恢复。

审计字段至少包括 id、actor_id、actor_name、action、target_type、target_id、request_id、operation_id、result、error_code、reason、before_summary、after_summary、ip、user_agent_hash、created_at、detail_json。摘要只允许安全字段，禁止密码、token、密钥、原文请求体和完整敏感 metadata。操作失败、部分成功、重试和清理都要有可查询记录。审计保留期默认 180 天，清理授权、范围、数量和 operation_id 写入保留期控制记录和 operation_events，不能把清理当作无痕删除。

### 4.6 研讨状态、租约与强制取消

状态定义沿用当前服务实现并统一终态：

| 分类 | 状态 | 规则 |
|---|---|---|
| 存续 | created、round_done、round_error、error | 可根据现有协议接受命令；round_error/error 是否可恢复由命令状态和快照决定 |
| 执行中（派生指标） | 存续会话且命令状态 running、租约有效 | running 属于命令状态，不向 discussion_sessions 新增同名状态；按 session_id 去重统计 |
| 失败待恢复 | round_error、可恢复的 error | 管理员可发起恢复任务，不能只改数据库字段 |
| 终态 | finished、cancelled | 禁止新命令；finished 由业务完成事件写入，cancelled 由管理取消写入 |

恢复流程在事务内再次检查 status、lease_until、lease_owner 和 generation；只允许无租约或过期租约，递增 generation，生成新的 recovery operation，并将可重试 pending/running 命令交给明确的 recovery worker。旧 worker 持有的 owner/generation 组合立即失效，任何写事件前都要再次校验。无客户端 WebSocket 时，后端 recovery worker 仍可执行并把事件写入数据库；若部署未启用 worker，返回 409 RECOVERY_WORKER_UNAVAILABLE，不能假装恢复成功。

强制取消在一个事务中封闭新命令入口、将状态写为 cancelled、清空 lease_owner/lease_until、递增 generation、将 pending/running 队列按规则标为 cancelled，并发布可被前端识别的 discussion.cancelled 事件。已经发出的模型请求无法撤回时，继续按真实 usage 结算；返回结果若 generation 已失效则丢弃，不得写回新的事件或摘要。恢复与取消并发时只有一个事务获胜，另一个返回 409。

### 4.7 数据集清理范围

清理服务接受显式 scope，至少区分 datasets、sessions、files、reservations、audit_logs、operation_events。purge-expired-datasets 不能直接调用同时删除会话、事件和命令的旧组合函数。

- 数据集在研讨活动租约或非终态会话中被引用时，普通删除返回 409 DATASET_IN_USE；过期清理记录 skipped_active_session，不直接删除；
- 已启动研讨使用已保存的 revision/summary 快照，不因数据集物理删除自动清除会话快照；需要重新读取原始数据的恢复任务若快照不足，进入 DATASET_SNAPSHOT_UNAVAILABLE；
- 删除数据集不删除会话事件、向量、PPT 或其他生成成果；页面展示实际影响范围；
- 过期且无活动租约的数据集按 scope 删除，返回 deleted、skipped、failed 明细；不提供“恢复”按钮。需要找回数据只能从备份/回收机制恢复；
- 会话过期清理先检查活动租约。非终态且有活动租约延后；无租约的过期会话先按取消/结算规则收口，再进入留存清理，不能把时间到期直接当成可删除。

### 4.8 文件登记、项目与 Chroma

files 是 services/ppt.py 生成 PPT 时写入的成果登记表。/admin/files 只展示登记记录及核验状态；generated_ppts 目录扫描仅用于发现 orphan_file、missing_registered_file 和 stale_temp_file，不会凭扫描结果制造可下载记录。删除 PPT 先登记 operation intent，再删除磁盘文件，文件删除成功后才移除登记；文件被占用、权限不足或磁盘错误返回 partial/failed，不能误报成功。已登记但磁盘缺失的记录保留为 missing，交由对账操作处理。

项目知识库的真实隔离键是 metadata.project_id。一个物理 collection 可含多个项目，一个项目也可跨多个 embedding 指纹集合。管理接口先发现所有可见 project_id（含 __legacy_unassigned__），再跨 qc_ 集合按 project_id 过滤。项目列表、文档列表、单文档删除和项目清空均使用该路径；不得以删除 collection 代替清空项目。物理 collection 仅只读列出名称、模型指纹和错误状态。

RAG 管理查询和删除使用 Chroma metadata-only client，不初始化 embedding client、不生成向量、不要求外部模型 key。Chroma 不可用时返回局部失败和数据新鲜度，其他看板卡片仍可展示。项目清空分批执行，与同项目导入互斥；跨集合部分失败保留 operation_id，可重试，验收确认其他项目向量不受影响、模型切换后已删除文档不复活。

### 4.9 用量、预算与未知占用

- SQLite 内部时间统一 UTC ISO 8601；前端默认 Asia/Shanghai 展示，所有查询区间为半开区间 [from, to)；
- 24h 按小时桶、7d/30d 按日桶，补齐空桶为零；30d by-model 只代表该区间，不与全历史 totals 直接比较；
- tokens 分 input、output、embedding 三类；已记账调用数按 usage_events 记录统计，不含尚未结算或未上报的调用；request_id 只用于去重和审计关联；
- 已结算历史成本保留事件发生时的 price_effective_from，不用当前价格重算；
- cost_usd 使用 Decimal/定点字符串，展示与 CSV 固定 6 位小数，允许误差统一为 0.000001；
- MAX_BUDGET_USD=0 时不计算除法，进度值为 null，显示“零预算 · 外部付费调用暂停”，不能解释成不限额或未设置；沿用预算校验，本地无计费路径另行显示。未知成本和 provider_overrun 单独告警；
- reset_provider_overrun 只把 provider_overrun 改为 overrun_cleared，不删除 usage_events，不把未知成本变成已知成本；
- sweep_stale_reservations 只释放超过阈值且状态为 reserved 的预留。usage_unknown 和 provider_overrun 永不因过期或实体删除自动释放，响应明确返回 released_reserved_count/amount 与 retained_unknown_count/amount。

---

## 五、数据模型、索引与迁移

### 5.1 新增管理模型

沿用 SQLite WAL、外键和事务风格，在 database.py 中引入 schema_versions 和分步迁移。计划新增或扩展以下表：

~~~sql
admin_users(
  user_id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
)

admin_sessions(
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES admin_users(user_id),
  token_hash TEXT NOT NULL UNIQUE,
  csrf_token_created_at TEXT NOT NULL,
  csrf_key_version INTEGER NOT NULL DEFAULT 1,
  csrf_generation INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_activity_at TEXT NOT NULL,
  last_request_at TEXT NOT NULL,
  reauthenticated_at TEXT,
  idle_expires_at TEXT NOT NULL,
  absolute_expires_at TEXT NOT NULL,
  ip TEXT,
  user_agent_hash TEXT,
  revoked_at TEXT
)

admin_login_throttles(
  throttle_key TEXT PRIMARY KEY,
  account_key TEXT NOT NULL,
  source_ip TEXT NOT NULL,
  failure_count INTEGER NOT NULL DEFAULT 0,
  window_started_at TEXT NOT NULL,
  locked_until TEXT,
  updated_at TEXT NOT NULL
)

audit_logs(
  id TEXT PRIMARY KEY,
  actor_id TEXT,
  actor_name TEXT NOT NULL,
  action TEXT NOT NULL CHECK(action IN (
    'LOGIN_SUCCESS','LOGIN_FAILURE','LOGIN_LOCKED','LOGOUT',
    'SESSION_REVOKE','SESSION_REVOKE_ALL','ADMIN_PASSWORD_CHANGE',
    'CONFIG_UPDATE','ACCESS_TOKEN_ROTATE','OVERRUN_RESET',
    'BUDGET_LIMIT_UPDATE','MAINTENANCE_RUN','DATASET_DELETE',
    'DATASET_PURGE_EXPIRED','DISCUSSION_LEASE_RECOVER',
    'DISCUSSION_FORCE_END','FILE_DELETE','PPT_DELETE',
    'RAG_DOCUMENT_DELETE','RAG_PROJECT_PURGE','AUDIT_RETENTION_PURGE',
    'LLM_PROBE','ADMIN_LOCAL_RECOVERY'
  )),
  target_type TEXT,
  target_id TEXT,
  request_id TEXT NOT NULL,
  operation_id TEXT,
  result TEXT NOT NULL CHECK(result IN ('REQUESTED','SUCCEEDED','PARTIAL','FAILED','DENIED')),
  error_code TEXT,
  reason TEXT,
  before_summary TEXT,
  after_summary TEXT,
  detail_json TEXT,
  ip TEXT,
  user_agent_hash TEXT,
  created_at TEXT NOT NULL
)

operation_events(
  id TEXT PRIMARY KEY,
  level TEXT NOT NULL CHECK(level IN ('info','warning','error')),
  category TEXT NOT NULL CHECK(category IN (
    'usage','maintenance','discussion','ppt','rag','config','security','system'
  )),
  event_key TEXT NOT NULL,
  message TEXT NOT NULL,
  operation_id TEXT,
  context_json TEXT,
  created_at TEXT NOT NULL
)

admin_operations(
  operation_id TEXT PRIMARY KEY,
  actor_id TEXT,
  kind TEXT NOT NULL,
  scope TEXT NOT NULL,
  idempotency_key TEXT,
  request_hash TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL CHECK(state IN (
    'pending','running','succeeded','partial','failed','cancelled'
  )),
  intended_json TEXT NOT NULL,
  result_json TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)

schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)
~~~

audit_logs 不允许任意 action，应用枚举与 SQL CHECK 双重约束。detail_json、context_json、intended_json 和 result_json 限制大小并只写安全摘要。管理端不删除 usage_events 或 reservations 的历史账本。

以上为逻辑字段清单，并非可直接执行的完整 DDL；AD-0.1 生成带 CREATE TABLE/迁移版本的脚本。detail_json/context_json 单条最大 4KB；操作意图和结果单条最大 64KB，大批量逐目标记录采用子表，不能截断恢复所必需的目标信息。

### 5.2 索引与查询约束

除主键/唯一键外，按真实过滤、排序和吊销路径建立索引：

- admin_sessions(user_id, revoked_at)、admin_sessions(revoked_at, absolute_expires_at)、admin_sessions(last_activity_at)；
- admin_login_throttles(source_ip, updated_at)、admin_login_throttles(account_key, updated_at)；
- audit_logs(created_at DESC, id DESC)、audit_logs(action, created_at DESC)、audit_logs(actor_id, created_at DESC)、audit_logs(request_id)；
- operation_events(created_at DESC, id DESC)、operation_events(category, created_at DESC)；
- admin_operations(state, updated_at)、admin_operations(actor_id, created_at DESC)、UNIQUE admin_operations(actor_id, kind, idempotency_key)（管理写操作三字段均非空）；
- datasets(expires_at, dataset_id)、datasets(created_at DESC, dataset_id DESC)；
- discussion_sessions(status, expires_at, session_id)、discussion_commands(session_id, status)（不对隐式 rowid 建索引；队列继续按既有 rowid 排序）；
- discussion_events(session_id, event_seq)；
- files(expires_at, file_id)、usage_events(created_at, provider, model)、reservations(status, created_at, id)；
- 若引入 usage_daily_rollups，主键为 day/provider/model，并为 day、provider/model 建查询索引。

所有列表接口采用稳定排序、最大 limit（默认 50，最大 200；日志和 CSV 另有专用上限）、offset 或 cursor 之一，不允许无界全表返回。大型日志、文件和 Chroma 扫描在后台线程/任务执行，不能阻塞事件循环或长时间持有写事务。

### 5.3 迁移和回滚

- 每次 schema 变更有单调版本号、迁移脚本、校验和和回滚说明；init_database 幂等只负责调用已登记迁移，不能以 CREATE TABLE IF NOT EXISTS 代替旧库升级；
- 迁移前使用 SQLite backup API 或一致性快照，先处理 WAL checkpoint/备份策略，同时记录 generated_ppts、日志和 Chroma 路径清单；
- 新旧版本兼容期明确：旧代码缺少管理表时仍可读业务表；新代码检测缺失表时管理功能安全关闭并返回 503；迁移失败自动回滚事务并保留旧库备份；
- 配置写入保留上一个 .env 安全副本，候选 Settings 校验成功后才原子替换；进程环境覆盖字段不写入，内存 Settings 与文件结果一致后才提升 revision；
- 回滚软件可关闭管理路由、停止新操作并让旧 worker 完成/放弃，但不会复原已删除数据；文件和 Chroma 删除的恢复必须依赖快照或回收站；
- 发布前演练旧库升级、迁移失败、WAL 恢复、配置回退、pending operation 重启恢复和跨存储对账。
- 首版采用短暂停写的一致性备份：关闭新业务/管理写入，停止定时任务及任务领取，等待在途任务完成或按取消结算规则收口；关闭 Chroma 写入句柄后，使用 SQLite backup API 备份数据库并复制实际 Chroma 数据目录、PPT 文件、受保护配置和 CSRF 密钥。生成清单及校验和后恢复服务。仅列出文件路径不算备份；恢复必须使用同一快照批次，并吊销全部旧管理会话。
- 保留默认值：operation_events 90 天，audit_logs 180 天；已终态 admin_operations 保留 180 天，pending/running/partial 及尚待处理 failed 操作不得按 TTL 删除；过期/吊销 admin_sessions 保留 7 天后清理。登录限制记录在锁定过期且 24 小时无更新后清理；日志沿用 2MB×4 文件的轮转上限。审计清理前先提交 AUDIT_RETENTION_PURGE 意图，清理边界固定为任务启动前截止时间，最终结果记录不落入本次删除范围。

---

## 六、后端 API 与模型契约

### 6.1 通用契约

所有管理接口前缀为 /api/admin，除 login 外依赖 verify_admin。响应使用明确 Pydantic 模型，不直接序列化数据库 Row。错误统一为：

~~~json
{"code":"ERROR_CODE","message":"面向用户的说明","request_id":"...","details":{}}
~~~

状态码固定语义：401 未登录/会话失效，403 CSRF/IP/权限拒绝，404 资源不存在，409 状态、scope、revision 或幂等冲突，422 字段校验失败，429 限流/锁定，503 管理关闭、依赖不可用或审计不可用。分页返回 items、total、limit、offset 或 next_cursor；total 不可用时明确 total_is_estimate。

规划中的模型包括 AdminLoginRequest、AdminSessionView、AdminMeResponse、DashboardOverview、TrendPoint、ActivityEventView、UsageSummary、UsageByModelRow、ReservationView、DatasetListItem、DatasetDetail、DiscussionListItem、DiscussionEventView、CommandView、FileRecordView、RagProjectView、RagDocumentView、HealthView、LogChunk、MaintenanceOperation、ConfigView、ConfigUpdateRequest、AuditLogView 和统一 ErrorResponse。每个模型只包含本节允许字段。

### 6.2 认证

| 方法与路径 | 请求/响应 | 规则 |
|---|---|---|
| POST /api/admin/auth/login | JSON username、password；返回 user、csrf_token、server_time、idle_expires_at、absolute_expires_at | Origin 精确校验；独立限流；成功下发 sid；失败统一 401/429 |
| POST /api/admin/auth/logout | CSRF；返回 revoked=true | 吊销当前会话，清 Cookie；重复调用稳定成功 |
| GET /api/admin/auth/me | 返回安全用户信息、会话截止时间、csrf_token、server_time | 不延长空闲；为页面刷新同步内存 token |
| POST /api/admin/auth/activity | 空 JSON；返回最新截止时间 | 仅真实交互调用，CSRF；不突破 8 小时绝对寿命 |
| POST /api/admin/auth/change-password | old_password、new_password、reason | 验证旧密码和策略；审计与哈希更新同事务；吊销全部会话并清当前 Cookie，返回 relogin_required=true |

### 6.3 看板与用量

| 方法与路径 | 请求/响应 | 规则 |
|---|---|---|
| GET /api/admin/dashboard/overview | DashboardOverview | 聚合健康、预算、今日/累计用量、存续/执行/待恢复会话、PPT 登记数、磁盘和新鲜度 |
| GET /api/admin/dashboard/trends | range=24h/7d/30d、metric=cost/tokens/requests；返回补齐空桶的 TrendPoint | UTC 半开区间；不把 30d 与全历史 totals 混算 |
| GET /api/admin/dashboard/activity | limit/offset、level/category；返回 ActivityEventView | 事件去重后的动态流，安全 context，稳定倒序 |
| GET /api/admin/usage/summary | range/from/to；返回 UsageSummary | Decimal 精度、未知成本和 overrun 单独字段 |
| GET /api/admin/usage/by-model | 时间范围、provider、model、分页 | provider/model 分组，tokens 三类分列 |
| GET /api/admin/budget/reservations | status、时间、分页 | status 枚举含 reserved、usage_unknown、settled、released、provider_overrun、overrun_cleared |
| POST /api/admin/budget/reset-overrun | reason、confirm_text、近期密码确认 | CSRF；只转状态并审计，不抹成本 |
| PUT /api/admin/budget/limit | expected_revision、max_budget_usd | 先校验；0 为合法但进度不计算；配置冲突返回 409 |
| GET /api/admin/usage/export.csv | 与页面相同的筛选、scope=filtered/all、最大范围和行数 | UTF-8 BOM；固定列、时间/金额格式；公式前缀转义；Content-Disposition 文件名服务端生成 |

CSV 约定：默认导出当前筛选结果，最多 100000 行、最多 90 天，按 created_at、id 稳定排序；列包括时间、provider、model、input_tokens、output_tokens、embedding_tokens、cost_usd、request_id（按安全规则截断）。全量导出需明确 scope=all 并在页面二次确认。以 =、+、-、@ 开头的文本字段增加单引号防止公式注入，导出与页面同一查询服务。

### 6.4 数据集

| 方法与路径 | 请求/响应 | 规则 |
|---|---|---|
| GET /api/admin/datasets | expired、分页；DatasetListItem | 只返回文件名、revision、confirmed_revision、行列统计、TTL、状态 |
| GET /api/admin/datasets/{dataset_id} | DatasetDetail | 列名和清洗报告允许字段；不返回 raw_rows_json/current_rows_json 原文 |
| DELETE /api/admin/datasets/{dataset_id} | reason、confirm_text、idempotency_key | in-use 返回 409；scope 仅该 dataset；数据库写与审计同事务 |
| POST /api/admin/datasets/purge-expired | scope=datasets、dry_run、confirm_text、idempotency_key | 返回 deleted/skipped/failed、数量和 operation_id；不联动删除会话/事件 |

### 6.5 研讨会话

| 方法与路径 | 请求/响应 | 规则 |
|---|---|---|
| GET /api/admin/discussions | status、存续分类、分页 | status 只使用 created/round_done/round_error/error/finished/cancelled，执行中为命令与租约派生字段 |
| GET /api/admin/discussions/{id}/events | after_seq、limit、cursor | 事件内容走允许字段和 PII 掩码 |
| GET /api/admin/discussions/{id}/commands | status、分页 | payload/error 仅安全摘要，长内容截断 |
| POST /api/admin/discussions/{id}/lease-recover | reason、confirm_text、idempotency_key | stale/无 owner 才允许；递增 generation；调度 recovery worker |
| POST /api/admin/discussions/{id}/force-end | reason、confirm_text、idempotency_key | 事务内取消、封队列、作废租约；终态或并发冲突返回 409 |

### 6.6 成果与 PPT

| 方法与路径 | 请求/响应 | 规则 |
|---|---|---|
| GET /api/admin/files | kind=ppt、登记状态、分页；FileRecordView | files 是登记源，显示 ready/expired/missing 状态；orphan/temp 仅在独立对账结果中展示，不暴露绝对路径 |
| GET /api/admin/ppts | files 的 PPT 视图 | 不把目录扫描结果当登记；可显示目录对账结果 |
| GET /api/admin/ppts/{file_id}/download | 二进制流 | 先管理鉴权，再复用 resolve_download 的登记、过期和目录边界检查，不跳到要求业务令牌的 URL |
| DELETE /api/admin/ppts/{file_id} | reason、confirm_text、idempotency_key | 先意图后磁盘删除；占用/权限失败返回 partial/failed，不误删登记 |

### 6.7 项目知识库

| 方法与路径 | 请求/响应 | 规则 |
|---|---|---|
| GET /api/admin/rag/projects | 分页；RagProjectView | 跨 qc_ 集合发现项目，展示去重文档/块数、legacy 未归属、数据新鲜度 |
| GET /api/admin/rag/projects/{project_id}/documents | 分页、文档筛选 | metadata-only；跨集合按 project_id 过滤 |
| DELETE /api/admin/rag/projects/{project_id}/documents/{document_id} | reason、confirm_text、idempotency_key | 只删该项目该文档的全部 chunks |
| POST /api/admin/rag/projects/{project_id}/purge | reason、confirm_text、batch_size、idempotency_key | 跨集合分批删除；与同项目导入互斥；返回部分失败 operation |
| GET /api/admin/rag/collections | 物理集合只读信息 | 不提供按 collection 删除；依赖不可用时局部失败 |

### 6.8 系统、日志与维护

| 方法与路径 | 请求/响应 | 规则 |
|---|---|---|
| GET /api/admin/system/health | HealthView | 本地检查进程、DB/WAL、磁盘、Chroma metadata；不发真实模型请求 |
| POST /api/admin/system/probe/llm | provider/model、reason、confirm_text | 显式主动探测，CSRF、审计、预算控制、超时和短缓存；未探测为 unknown |
| GET /api/admin/system/logs | level、tail、cursor、max_bytes、include_rotated | 固定目录；游标含文件身份/字节位置；增量 tail、轮转重置、长行截断 |
| POST /api/admin/system/maintenance | scope、dry_run、reason、confirm_text、idempotency_key | 共享互斥；同步超时返回 operation_id；返回每步 success/failed/skipped/unknown |
| GET /api/admin/system/maintenance/{operation_id} | MaintenanceOperation | 查询超时/部分完成结果和重试状态 |
| GET /api/admin/system/storage | StorageView | data、generated_ppts、logs 和剩余空间；扫描不阻塞请求 |

日志 API 只能读取服务端固定 app.log 及明确允许的轮转文件，禁止任意路径。cursor 至少包含文件名/文件身份、字节偏移和生成时间；文件轮转、截断或身份变化时从安全位置重置。tail 从末端增量读取，不每次扫描整文件；单次最大字节数 1MB，超长行截断并带 truncated 标记，多行异常按结构化记录安全返回。level 过滤在服务端执行，日志中的 token、URL 参数、Authorization、Cookie、密钥模式和多行异常统一脱敏。

### 6.9 安全中心、配置与审计

| 方法与路径 | 请求/响应 | 规则 |
|---|---|---|
| GET /api/admin/security/sessions | 分页；SessionView | 仅安全 IP/UA 摘要、最后活动和截止时间 |
| POST /api/admin/security/sessions/{id}/revoke | reason、confirm_text | 可吊销他人；不得清除操作者自己的 Cookie |
| POST /api/admin/security/sessions/revoke-all | reason、confirm_text | 明确语义为吊销“其他全部会话”，当前会话保留；当前会话用 logout |
| GET /api/admin/security/settings | SecuritySettingsView | 只读掩码、enabled/source，不回显秘钥 |
| POST /api/admin/security/rotate-access-token | current_password、reason、confirm_text | 近期密码确认；一次性安全展示；新 HTTP/新 WS 拒绝旧令牌，既有 WS 保持至关闭 |
| GET /api/admin/config | ConfigView、revision、字段来源 | 仅允许字段；环境变量覆盖项标记 env_override |
| PUT /api/admin/config | expected_revision、values、reason | 候选 Settings 先校验，409 防覆盖，配置意图/结果审计 |
| GET /api/admin/audit | action、actor、date_from、date_to、result、分页 | 默认倒序 100 条；只返回安全 detail；查询与保留策略一致 |

配置允许字段、范围、是否需重启和来源在 ConfigView 中逐字段声明。进程环境变量优先于 .env 时，PUT 对该字段返回 409 CONFIG_ENV_OVERRIDE；写入 .env 后必须重建 Settings、依赖和内存缓存，只有内存/文件/revision 一致才返回成功。令牌轮换返回一次性展示值和配置更新提示，响应丢失时只能通过本机恢复/重新轮换取得新值，不能在普通 GET 中回显。

### 6.10 操作查询、幂等与近期身份确认

- 所有管理写请求使用 Idempotency-Key；数据库对 actor_id、kind、key 作唯一约束，同时保存规范化请求摘要 request_hash（不得包含明文密码/令牌）。相同 key、相同请求返回原 operation_id 与已存在结果；同 key 不同目标或请求返回 409 IDEMPOTENCY_CONFLICT。客户端在发请求前生成 key，响应丢失时仍可按 key 查询，不能依赖尚未收到的 operation_id。
- GET /api/admin/operations/{operation_id} 返回目标摘要、状态、各步骤统计、attempt_count、error_code 和可重试标志；GET /api/admin/operations?key=... 查询当前管理员的操作。仅返回安全结果，改密/轮换等秘密永不从查询接口重放。
- POST /api/admin/operations/{operation_id}/retry 使用 CSRF、reason、新的重试请求幂等键，并重新校验原 scope 和当前权限。只允许 failed/partial 且 retryable 的操作，沿原 operation_id 增加 attempt_count，从未完成步骤恢复；成功步骤不重复产生副作用。pending/running 返回 409 OPERATION_RUNNING，已成功返回原结果。
- 幂等记录随终态 operation 保留 180 天；凭据修改和令牌轮换不做隐式自动重试。轮换成功但响应丢失，查询只告知已完成及重新接入步骤，重新轮换必须由管理员显式发起新操作。
- POST /api/admin/auth/reauth 校验 current_password，使用有效会话、CSRF 和独立限流，在服务端记录 reauthenticated_at。密码只用于即时校验，不写审计/operation。预算复位、凭据轮换和高危批量清理要求最近 5 分钟内再认证，否则返回 403 ADMIN_REAUTH_REQUIRED；改密在同一请求验证旧密码。数据库会话新增 reauthenticated_at 字段。
- SQL-only 操作对已删除目标重复请求按幂等 key 返回原成功结果；新请求访问不存在目标返回 404。外部操作超出 3 秒同步预算时返回 202 及 operation_id；同步、异步和重试共享同一状态定义和审计链。

---

## 七、前端页面与交互

### 7.1 路由、作用域与布局

管理路由独立懒加载：

~~~text
/admin/login
/admin/overview
/admin/usage
/admin/budget
/admin/datasets
/admin/discussions
/admin/files
/admin/rag
/admin/logs
/admin/system
/admin/security
/admin/config
/admin/audit
~~~

当前 App.tsx 由 WizardProvider 包裹整个 RouterProvider。实施时将 WizardProvider 移至业务路由子树，管理路由位于其外部；AdminGuard 只调用管理 me，不初始化 WizardContext、不读取业务快照、不发业务 API 请求。生产代理必须支持 /admin/* 直接刷新回退到 SPA，API 路径不能被 SPA fallback 吞掉。

AdminLayout 包含 48px 顶栏、与顶栏控制条同高的 48px 侧栏首层导航基准、折叠菜单、面包屑、会话倒计时和退出按钮。严格执行预览约束：去掉三色点、加强整体阴影、延续玻璃 token；危险操作按钮、键盘焦点和错误色需满足可读性。

frontend/src/api/admin.ts 使用带 credentials 的同源客户端，登录/me 响应写入内存 csrf token，拦截器只为管理写请求回填 X-CSRF-Token；轮询请求不带用户活动标记。401 跳登录、403 CSRF 先刷新 me、503 显示关闭/未初始化/依赖不可用，不能循环重试。

### 7.2 页面清单

| 页面 | 主要内容 | 必须交付的反馈 |
|---|---|---|
| 登录 | 账号密码、锁定倒计时、来源/关闭提示 | 统一错误、回跳原目标、成功后 me 同步 token |
| 总览 | 健康、预算、今日成本、存续/执行/待恢复会话、PPT、磁盘、趋势和动态流 | 3 分钟轮询不续期；局部依赖失败标记新鲜度 |
| 用量 | 时间范围、按模型、tokens、成本、CSV | 空桶、零预算、未知成本、导出范围一致 |
| 预算 | 预留账本、状态筛选、超额复位、预算上限 | 二次确认、近期密码确认、操作进度和结果 |
| 数据集 | 列表、统计详情、过期清理、单删 | 原始行不出站；in-use 409；清理逐项统计 |
| 会话 | 状态、事件、命令、租约恢复、强制取消 | generation/冲突反馈；终态按钮关闭；在途成本说明 |
| 文件与成果 | PPT 登记、核验、下载、删除 | missing/orphan 显示；占用失败不显示成功 |
| 知识库 | 项目卡、文档列表、单文档删、项目清空、collection 只读 | 跨集合进度、部分失败、其他项目保护 |
| 运维日志 | level、tail、暂停、轮转游标、手动维护 | 增量读取、脱敏、超时可查 operation_id |
| 系统 | 本地健康、显式探测、存储 | unknown/degraded 与局部失败，不暗发模型请求 |
| 安全中心 | 会话、其他会话全吊销、令牌轮换、改密 | 轮换影响范围、一次性展示、改密后重新登录 |
| 配置 | 允许字段、revision、来源、重启提示 | expected_revision 冲突、env_override、非法配置不落盘 |
| 审计 | action/actor/result/时间筛选 | 只读脱敏、operation 链接、稳定分页 |

### 7.3 高危操作统一交互

删除、清空、强制取消、租约恢复、预算复位、改预算、配置写入、令牌轮换、会话吊销和手动维护均使用同一 ConfirmOperation 组件。页面必须显示目标、scope、影响范围、不可逆性、operation_id 查询方式和 reason；高危项再要求输入目标名称/确认词，改密和令牌轮换要求近期密码验证。重复提交使用 idempotency_key，网络超时后先查询 operation_id，不能把按钮重复点击当成新的成功操作。

前端所有日志、事件、命令错误、RAG metadata 和审计详情以纯文本渲染；不将日志当 HTML，不信任服务端 message 中的标签。下载、配置和会话响应不缓存。

---

## 八、功能模块逐项验收口径

### 8.1 总览、健康与动态流

overview 的每张卡都有 data_source、calculated_at、freshness。活跃指标拆为存续会话、执行中会话、失败待恢复会话；finished/cancelled 不计入活跃。健康只做本地无费用检查，主动 LLM 探测单独触发并记预算/审计。Chroma 失败时其他卡正常返回 degraded。

动态流从核心生产者写入 info/warning/error；同一 event_key 在 5 分钟抑制窗口内去重，预算告警只在阈值跨越时生成，恢复生成 recovery 事件。首发只承诺页面展示和结构化记录，不承诺尚未接入的外部短信、邮件或即时通知。

### 8.2 用量、预算与 CSV

SQL 直查与接口都采用 UTC 半开区间、固定桶粒度和 Decimal 汇总；空库返回空数组与稳定的零/unknown 字段。预算为零不除零；usage_unknown、provider_overrun 和 overrun_cleared 分开统计。CSV 与页面使用同一过滤服务，筛选、时间、金额、编码、公式防护和最大范围全部验收。

### 8.3 数据集

详情只包含允许字段，raw_rows_json、current_rows_json 原文永不返回。单删和过期清理只作用于 datasets scope；遇到活动租约或非终态引用明确跳过/409。返回 deleted、skipped、failed、operation_id，审计逐项可查。删除后会话快照、向量、PPT 的保留行为在页面说明并通过回归验证。

### 8.4 会话

完成会话状态必须为 finished，管理员取消状态为 cancelled；不存在 ended。恢复需要 generation 递增、recovery worker 领取、旧 worker 写回拒绝和前端事件可见。取消需要停止新命令、作废租约、处理队列；在途模型请求按真实 usage 结算，迟到响应不得写回。并发恢复/取消/执行只允许一个事务成功。

### 8.5 PPT 成果

files 登记、磁盘文件和过期时间三者状态可核对。目录孤儿不出现在可下载列表；登记缺失标记 missing。删除遇到文件占用、权限或磁盘错误返回 partial/failed，重试可继续，不移除错误登记。管理员下载必须先过管理鉴权并调用 resolve_download 的边界检查。

### 8.6 项目知识库

项目发现直接读取 metadata，模型配置或 embedding key 缺失不能阻断列表/删除。项目文档数按 document_id 去重，块数单独展示。单文档删除和项目清空跨所有相关物理集合分批执行，与导入互斥；部分失败可查询/重试。__legacy_unassigned__ 明确展示并默认不参与任意项目清空。

### 8.7 日志与维护

日志 cursor 对轮转、截断、多行和超长行有稳定语义；tail 为增量读取，用户不能指定路径。手动维护与定时任务共享锁/operation 去重，支持 dry_run、超时查询和重试。返回结构固定包含各 scope 的 attempted、succeeded、skipped、failed、unknown，即使空库也返回全部键。reserved 可释放，usage_unknown/provider_overrun 保留并显示数量/金额。

### 8.8 安全、配置和审计

改密全吊销、清 Cookie、重新登录；吊销其他会话不能清操作者 Cookie；轮换新 HTTP/WS 令牌规则与既有 WS 保持到关闭前一致。配置候选先校验，expected_revision 冲突为 409，环境覆盖字段不可写，失败不得污染 .env 或内存 Settings。所有管理敏感写操作均有 REQUESTED/结果审计链，审计失败阻断数据库写并使外部操作停在可恢复意图状态。

---

## 九、实施路线图与任务

工期仅在人员投入、组件复用和迁移演练确认后估算；以下是依赖顺序，不是已承诺的上线日期。每个阶段完成独立门禁后才进入下一阶段。

### P0 设计定稿与安全基础

| 任务 | 内容 | 阶段门禁 |
|---|---|---|
| AD-0.1 | schema_versions、管理表、CHECK、索引、旧库迁移和 WAL 备份脚本 | 空库/旧库幂等；失败自动回滚且旧业务可用 |
| AD-0.2 | admin_security：bootstrap、DB 权威、PBKDF2、会话、Origin/JSON、CSRF、30 分钟用户活动空闲、8 小时绝对寿命 | 首次初始化/重启/本机恢复闭环；轮询不续期 |
| AD-0.3 | 登录限流、锁定、可信代理 IP、密码校验并发和 ADMIN_ENABLED 503 | 账号/IP 限流、未知账号一致、IPv4/IPv6/CIDR 校验 |
| AD-0.4 | audit、admin_operations、事件枚举和事务/补偿框架 | DB 写与审计同事务；外部动作意图可恢复 |
| AD-0.5 | 管理请求/响应模型、错误码、verify_admin、同源代理和 App.tsx 向导作用域调整 | 管理直达不触发 WizardContext/业务请求；刷新回退正确 |
| AD-0.6 | PPT 登记模型核对、metadata-only RAG 管理路径、会话状态/generation 规则 | files、project、finished/cancelled 口径经样例数据核验 |

### P1 可信只读后台

| 任务 | 内容 | 阶段门禁 |
|---|---|---|
| AD-1.1 | overview/trends/activity、健康和动态流 | 直查一致、空桶/局部失败/新鲜度正确 |
| AD-1.2 | usage/summary/by-model/reservations 和 CSV | 区间、Decimal、零预算、unknown、公式防护正确 |
| AD-1.3 | datasets/discussions/files/rag 只读列表与详情 | 分页稳定、全字段脱敏、跨集合项目清单正确 |
| AD-1.4 | system/storage/logs 只读和游标 | 不任意读路径、不发模型请求、轮转和 tail 正常 |
| AD-1.5 | P1 页面、AdminLayout、审计查询页和安全回归基础 | 1440/768/390 无溢出；审计可检索；首批写操作前置校验可用 |

### P2 逐项开放管理写操作

| 任务 | 内容 | 阶段门禁 |
|---|---|---|
| AD-2.1 | 预算复位、预算上限和配置更新 | 高危确认、expected_revision、env_override、审计链 |
| AD-2.2 | 数据集单删/过期清理和维护 scope 服务 | in-use 保护、部分完成、unknown 保留、定时/手动互斥 |
| AD-2.3 | PPT 下载/删除与目录对账 | 登记/磁盘一致性、占用失败、重试可追踪 |
| AD-2.4 | 项目文档单删/项目清空 | 跨集合隔离、metadata-only、导入互斥、部分失败 |
| AD-2.5 | 会话租约恢复、强制取消和 recovery worker | generation 竞争、旧 worker 拒写、队列关闭、在途成本保留 |
| AD-2.6 | 安全中心、改密、吊销会话、令牌轮换和显式 LLM 探测 | 改密全吊销；既有 WS 规则与前端重配说明一致 |

审计查询、写操作权限/CSRF/状态并发验证随首批 P2 写操作同时上线，不把基本安全能力推迟到收尾阶段。

### P3 发布收口

| 任务 | 内容 | 阶段门禁 |
|---|---|---|
| AD-3.1 | 审计/事件/日志/会话保留清理、告警去重和恢复事件 | scope、数量、授权、清理留痕；未知占用不归零 |
| AD-3.2 | 旧库升级、WAL/文件/Chroma 快照恢复和 pending operation 演练 | 迁移失败、配置回滚、跨存储对账和软件回滚可验证 |
| AD-3.3 | 同源代理浏览器 E2E、业务向导回归、并发与性能门禁 | 业务无明显退化，P95 达到定义目标 |
| AD-3.4 | 部署文档、故障处理、令牌轮换后的前端重建/重配步骤 | 新旧 HTTP/WS 行为、503 引导、刷新回退均有操作手册 |

### P4 可选分析能力

- 仅在 P1/P3 性能数据证明需要时增加 usage_daily_rollups。日表用于 7d/30d 聚合，24h 小时趋势仍需小时数据或实时聚合，不能直接用日表替代；
- 成本预测、预算阈值告警与分析导出独立评估；
- PDF 报表另行选择 headless Chromium、LibreOffice 或服务端渲染方案，明确部署依赖、字体和版式验收，不以 python-pptx 直接承诺 PDF。

---

## 十、测试、验收与发布门禁

### 10.1 后端测试矩阵

| 用例组 | 必测场景 |
|---|---|
| 初始化与认证 | 首次 bootstrap、DB 权威、重启、禁用、账号缺失、无效哈希、本机恢复、改密全吊销 |
| Cookie/CSRF | Origin/JSON、Cookie 属性、Path、Secure、SameSite、跨会话 token、重复 Cookie、过期刷新、PATCH 和多标签页 |
| 会话 | 30 分钟用户活动空闲、轮询不续期、后台休眠恢复、8 小时绝对截止、吊销他人不影响自己 |
| 限流 | 全局业务限流分流、IP/账号失败计数、成功清零、锁定、Retry-After、可信代理和 IPv4/IPv6 |
| 授权 | 无会话 401、IP/CSRF 403、业务令牌不可访问管理、管理 Cookie 不访问业务写接口、未配置 503 |
| 审计 | 每个白名单 action、REQUESTED/结果链、事务回滚、审计失败阻断、敏感字段禁写 |
| 状态/租约 | finished 不计活跃、cancelled 封队列、恢复 generation、旧 worker 拒写、恢复/取消竞争和无 worker |
| 删除/维护 | scope 隔离、in-use、文件占用、磁盘满、Chroma 部分失败、定时/手动互斥、超时 operation 查询 |
| RAG | 项目跨集合、collection 多项目、legacy 未归属、metadata-only、模型 key 缺失、删除后不复活 |
| 数据/成本 | UTC 半开区间、跨日、空桶、零预算、历史价格、unknown/provider_overrun/overrun_cleared |
| 脱敏 | 文件/列名/报告、事件、命令 payload/error、RAG metadata、运营 context、审计、URL 参数和多行日志 |
| 配置 | 非法候选不落盘、expected_revision 409、环境覆盖、内存/文件一致、配置回滚、响应丢失重试 |

### 10.2 前端与浏览器测试

- AdminGuard 覆盖未登录、已登录、ADMIN_DISABLED、ADMIN_NOT_INITIALIZED、依赖 degraded；
- 登录/me 内存 token、CSRF 403 刷新、401 跳转、轮询不带用户活动标记、绝对 TTL 倒计时；
- 高危确认、输入目标名称、近期密码验证、幂等键和网络超时查询 operation_id；
- 所有页面覆盖空态、加载态、错误态、局部失败、纯文本日志、CSV 下载和公式防护；
- 生产同源代理下直接打开/刷新每个 /admin 路由；业务向导全流程、WebSocket 重连和令牌轮换后前端重建；
- 1440、768、390 三档布局、键盘焦点、对比度和预览约束：无三色点、48px 顶栏/侧栏控制条、阴影层次一致。

### 10.3 性能与可靠性

使用明确硬件、SQLite WAL、数据量、并发数、冷热缓存状态和统计次数记录结果。至少以 10 万条 usage_events、1000 条审计、轮转日志和多物理 collection 进行并发业务请求测试；P1 看板接口 P95 目标为小于 2 秒，维护及耗时外部动作走异步 operation；CSV 导出按日期范围和行数上限流式响应，超限返回明确错误并提示缩小范围，日志和 Chroma 扫描不阻塞业务事件循环。若目标未达到，先记录瓶颈，再决定是否引入 P4 预聚合。

### 10.4 发布门禁

最终正式发布前须全部通过；各阶段按第九章门禁及以下当期适用项验收：

1. 首次初始化 → 登录 → me/CSRF → 改密 → 重启 → 旧密码失效 → 本机恢复闭环；
2. 同源代理 Cookie 可设置、携带、清除，非可信 Origin 拒绝，管理页直接刷新正常；
3. 管理写操作审计可查询，数据库写与审计原子，外部失败可追踪/重试，无误报成功；
4. finished/cancelled、租约 generation、旧 worker、在途成本和队列处理符合声明；
5. 删除只影响明确 scope，跨项目隔离，登记/磁盘/向量状态可对账；
6. 配置冲突、非法设置、env_override、令牌轮换和既有 WS 行为符合契约；
7. 数据口径、CSV、空库、零预算、未知占用和全部出站字段脱敏一致；
8. 旧库迁移、WAL/文件/Chroma 恢复、维护互斥、并发性能和业务回归通过；
9. 后端 pytest/ruff、前端 vitest/e2e、npm run build 等既定工程检查全绿。上述检查属于实施阶段验收，本次方案修订不执行。

---

## 十一、风险与对策

| 风险 | 对策 |
|---|---|
| 环境变量与数据库再次分叉 | 仅首次 bootstrap 读环境；数据库权威；本机恢复留痕 |
| Cookie/XSS/CSRF | HttpOnly、Strict、Secure、同源代理、Origin、会话绑定内存 token、CSP 和纯文本渲染 |
| 轮询无限续期 | 用户活动标记与请求活动分离，服务端维护 30 分钟 idle 和 8 小时 absolute |
| 业务令牌绕过管理员审计 | 能力矩阵明确遗留入口和承诺边界；后续统一审计需另立改造 |
| 审计失败导致无记录写入 | 数据库写和审计同事务；外部动作先 intent，关键审计失败则阻断 |
| 删除误伤数据/项目 | 显式 scope、in-use 保护、项目 metadata 过滤、文件/向量对账和操作确认 |
| 租约恢复双执行者 | generation 原子递增，worker 写前校验，恢复/取消使用事务竞争 |
| 令牌轮换中断现有连接 | 明确新 HTTP/WS 失效、既有 WS 保持至关闭；前端重建/重配步骤 |
| SQLite 查询或扫描拖慢业务 | 索引、分页、短读事务、异步扫描、性能 P95 门禁 |
| 日志/审计泄露秘密 | 字段白名单、URL/多行异常脱敏、no-store、前端纯文本 |
| TTL 清理误释放未知成本 | reserved 与 usage_unknown/provider_overrun 分开，未知占用永不自动释放 |

---

## 十二、工程文件、配置与审核映射

### 12.1 新增/修改文件清单

以下是待实施文件，不代表当前已经创建或修改：

~~~text
backend/app/core/admin_security.py                 新增：bootstrap、会话、CSRF、限流和锁定
backend/app/services/audit.py                      新增：白名单审计、查询、留存
backend/app/services/admin_operations.py           新增：operation intent、幂等、补偿和对账
backend/app/services/events.py                     新增：运营事件流和告警去重
backend/app/services/admin_metrics.py              新增：看板、时间桶、用量和存储聚合
backend/app/services/admin_cleanup.py              新增：带 scope 的手动/定时清理
backend/app/repositories/database.py               修改：schema_versions、管理表、索引、迁移入口
backend/app/models/admin_contracts.py              新增：管理请求/响应/错误模型
backend/app/api/endpoints/admin/                    新增：auth、dashboard、usage、datasets、
                                                     discussions、files、rag、system、security、
                                                     config、audit
backend/main.py                                    修改：唯一注册 /api/admin 路由和中间件顺序
backend/app/core/config.py                         修改：候选校验、revision、环境覆盖识别
backend/app/services/discussion_session.py         修改：cancelled、generation 恢复/取消防写回
backend/app/services/rag.py                        修改或抽取：metadata-only、跨集合项目操作
backend/app/services/ppt.py                        修改：登记/磁盘一致性和对账状态
backend/tests/test_admin_*.py                      新增：认证、审计、指标、操作、RAG、脱敏、迁移
scripts/gen_admin_password.py                      新增或修订：只生成 bootstrap 哈希
scripts/admin_local_recover.py                    新增：受控本机恢复流程
frontend/src/layouts/AdminLayout.tsx               新增：48px 顶栏/侧栏控制条和玻璃布局
frontend/src/routes/router.tsx                     修改：管理路由懒加载和守卫
frontend/src/App.tsx                               修改：WizardProvider 仅包业务路由子树
frontend/src/api/admin.ts                          新增：同源 Cookie、内存 CSRF、错误拦截
frontend/src/types/admin.ts                        新增：管理接口类型
frontend/src/pages/admin/*.tsx                     新增：登录及 12 个管理页面
frontend/src/components/admin/ConfirmOperation.tsx 新增：统一高危操作确认
frontend/src/test/admin*.test.tsx                  新增：守卫、API、登录、确认和布局
frontend/vite.config.*                             修改：开发同源代理
.env.example                                       修改：ADMIN_* 说明
README.md                                          修改：bootstrap、同源代理、恢复和令牌轮换
~~~

路由集中在 backend/main.py 注册，不把当前不存在的 endpoints/__init__.py 列为必改文件。管理 Pydantic 契约、前端类型、错误码、联调样例和 Settings/App.tsx 均列入范围。

### 12.2 配置和交付说明

ADMIN_ENABLED、ADMIN_BOOTSTRAP_USERNAME、ADMIN_BOOTSTRAP_PASSWORD_HASH、ADMIN_SESSION_IDLE_MINUTES、ADMIN_SESSION_ABSOLUTE_HOURS、ADMIN_LOGIN_RATE_PER_MINUTE、ADMIN_ALLOWED_IPS、ADMIN_CSRF_TOKEN_TTL_MINUTES、ADMIN_MAX_SESSIONS 写入 .env.example。bootstrap 哈希只用于首次创建；生产环境权限为仅服务账号可读。API_ACCESS_TOKEN 轮换后的新值只一次展示，前端业务构建变量/部署密钥按发布流程更新；管理端不保存或回显明文。

### 12.3 R01-R22 审核映射

| 审核项 | v2 决策与落点 | 任务/门禁 |
|---|---|---|
| R01 | 4.1、3.2：env 仅首次 bootstrap，admin_users 权威，ADMIN_ENABLED 独立，本机恢复；改密全吊销 | AD-0.2、AD-2.6；初始化闭环 |
| R02 | 4.2：登录 Origin+JSON，sid 属性明确，CSRF 从 login/me JSON 返回并存内存，服务端校验会话 token_hash 和 HMAC 派生值 | AD-0.2、10.1 Cookie/CSRF |
| R03 | 4.3：用户活动与轮询分离，30 分钟 idle、8 小时 absolute，服务端时间裁决 | AD-0.2；会话测试 |
| R04 | 2.2：遗留业务敏感入口保留并明确不承诺全系统审计；无业务令牌仅本机 | AD-0.5、10.1 授权 |
| R05 | 4.4：同源代理、管理/登录限流分流、可信代理 IP、账号/IP 锁定、并发哈希限制 | AD-0.3、P3 同源门禁 |
| R06 | 4.5、5.1：审计同事务，外部 operation intent/补偿，SQL CHECK，ACCESS_TOKEN_ROTATE | AD-0.4、10.1 审计 |
| R07 | 4.6、8.4：沿用 finished，管理取消为 cancelled，移除 ended | AD-0.6、AD-2.5 |
| R08 | 4.6：generation、恢复 worker、停止队列、终止事件、旧 worker 拒写和在途成本规则 | AD-2.5；状态/租约测试 |
| R09 | 4.8、6.6：files 仅 PPT 登记，目录只对账；下载复用 resolve_download，删除处理占用失败 | AD-0.6、AD-2.3 |
| R10 | 4.8、6.7：项目不是 collection，跨集合 project_id 过滤，metadata-only，不依赖 LLM 凭证 | AD-0.6、AD-2.4 |
| R11 | 4.7、8.3：清理按 scope，活动会话延后，快照/向量/成果保留，删除无在线恢复 | AD-2.2、AD-3.2 |
| R12 | 6.9、3.2：候选预校验、expected_revision/409、环境覆盖；旧令牌对新请求/新 WS 失效，既有 WS 到关闭 | AD-0.5、AD-2.6、AD-3.4 |
| R13 | 4.9、8.2：UTC、半开区间、桶粒度、token/request 口径、历史价格、Decimal、零预算 | AD-1.2；数据/成本测试 |
| R14 | 4.7、6.8、8.7：scope 清理、定时/手动互斥、operation 查询、逐步统计、空库稳定结构 | AD-2.2、AD-3.1 |
| R15 | 4.5、6.1、7.3：全出站字段白名单/脱敏、no-store、纯文本日志和 metadata | AD-1.3、10.1 脱敏 |
| R16 | 6.8、8.7：游标含文件身份/字节位、轮转重置、tail 增量、最大字节和路径固定 | AD-1.4；日志测试 |
| R17 | 6.8、8.1：本地健康与显式 LLM probe 分离，probe 单独审计/预算；未探测 unknown，Chroma 局部失败 | AD-1.1、AD-2.6 |
| R18 | 3.1、7.1、AD-0.5：WizardProvider 移到业务路由子树，管理直达不触发向导，SPA 刷新回退 | AD-0.5、10.2 |
| R19 | 5.2、10.3：按真实过滤排序建索引、分页上限、短事务/异步扫描、P95 条件和预聚合安排 | AD-0.1、AD-3.3、P4 |
| R20 | 5.3、9：schema 版本、旧库升级、WAL/文件/Chroma 备份、功能关闭和恢复演练；回滚不等于找回数据 | AD-0.1、AD-3.2 |
| R21 | 6.1、6.2-6.9、7.3：请求/响应模型、状态码、分页/排序/验证、幂等键和超时查结果 | AD-0.5、AD-2.x、10.1 |
| R22 | 4.9、8.7：只释放 stale reserved，返回释放与保留 unknown 数量/金额，禁止未知占用自动归零 | AD-2.2、AD-3.1 |

用户已批准预览并授权实施；代码、测试和迁移按上述任务及门禁推进，生产发布须在验收完成后执行。
