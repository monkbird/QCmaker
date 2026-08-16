# QCmaker 后端详细开发计划

> 版本：v1.2 ｜ 依据：已通读 `backend/` 全部源码（8 个端点 + 5 个服务 + 2 个智能体 + 入口/配置/中间件，共 18 个 Python 文件）
> 配套文档：《前端详细开发计划》（`frontend-dev-plan.md`），任务编号 BE-x / FE-x 互相引用

---

## 一、现状结论（已核实）

| 维度 | 实际情况 |
|---|---|
| 技术栈 | FastAPI + LangChain/LangGraph + ChromaDB + Pandas + python-pptx，栈本身合理，无需更换 |
| 代码规模 | 18 个 Python 文件，约 2 万字符，体量小 |
| 运行方式 | 必须从项目根目录 `uvicorn backend.main:app`（import 路径为 `backend.app.xxx`） |

### 问题清单（按严重级）

| 级别 | 编号 | 问题 | 证据 |
|---|---|---|---|
| 🔴 | B1 | **保存配置不生效**：`/config/update` 只写 `os.environ`，而所有服务读的是启动时快照的 `settings` 单例；改配置必须重启，且重启后 `os.environ` 的修改丢失（未写回 .env） | `endpoints/config.py` L43-62 vs `core/config.py` |
| 🔴 | B2 | **配置读取双轨**：`GET /config/` 读 `os.getenv`，服务读 `settings`，两者随时不一致；且 LLM 客户端有缓存（`self.llm`），key 变更后不重建 | `endpoints/config.py` L26-36、`agents/topic_consultant.py` L50-53 |
| 🔴 | B3 | **契约断裂**：后端要 `max_budget_usd`，前端提交 `max_budget`（静默丢弃）；后端只返回 `has_openai_key`，前端期望 `openai_api_key` 回显 | `endpoints/config.py` L9-15 vs `ConfigPanel.jsx` |
| 🔴 | B4 | **多智能体研讨是假的**：5 个 agent 全部返回硬编码"[模拟数据]"式字符串；moderator 用数消息条数的方式路由；`_get_llm()` 定义后从未被调用 | `agents/discussion.py` 全文 |
| 🔴 | B5 | **WebSocket 无会话**：每条用户消息都重启整个 graph，没有历史，研讨永远只有一轮 | `endpoints/discussion.py` L14-17 |
| 🔴 | B6 | **依赖缺失**：代码 import 了 `pydantic_settings`、`httpx`、`pypdf`、`langchain_text_splitters`，`requirements.txt` 未声明；Excel 读写还未显式声明 `openpyxl`/`xlrd` | `requirements.txt` vs 各文件 import |
| 🟡 | B7 | **依赖未锁定**：`requirements.txt` 仅列包名，无法保证 LangChain/LangGraph 等强耦合依赖在新环境中行为一致 | `requirements.txt` |
| 🟡 | B8 | PPT 服务接收 `chart_images` 但**完全未使用**；固定 4 页英文骨架；结论页文案写死 | `services/ppt.py` |
| 🟡 | B9 | 数据清洗只删空行/合计行，无缺失值/异常值处理，无清洗报告；`df['key']` 污染用户数据并流入图表 | `services/data_cleaning.py` |
| 🟡 | B10 | 图表服务：y 值不做数值转换、重复 x 不聚合、拦截器仅 1 条规则、无图表推荐接口 | `services/chart.py` |
| 🟡 | B11 | 路径安全：PPT 文件名直接拼接 `project_name`（路径注入）；`/ppt/download/{filename}` 无穿越校验 | `services/ppt.py` L62、`endpoints/ppt.py` L34-38 |
| 🟡 | B12 | PII 中间件定义了但从未注册到 app，发送给 LLM 的数据不过滤 | `middleware/pii.py`、`main.py` |
| 🟡 | B13 | RAG/搜索端点前端完全未接入；`TextLoader` 未指定编码，中文文档大概率 UnicodeDecodeError；ingest 临时文件无 finally 清理 | `endpoints/rag.py`、`services/rag.py` L41-45 |
| 🟢 | B14 | CORS 通配来源与凭证组合存在安全风险且行为容易产生误解；无日志（仍有 `print`）、无测试、无 token 用量统计（README 宣称的"Token 消耗监控与预算保护"代码中不存在） | `main.py`、`requirements.txt` |

**核心判断**：后端最痛的不是缺功能，而是「配置系统是断的（B1/B2/B3）+ 核心卖点研讨是模拟的（B4/B5）+ 全新环境无法可靠复现（B6/B7）」。

---

## 二、改造原则

1. 不换框架、不换 AI 编排栈（LangGraph 保留）
2. 顺序：先能跑且冻结契约（P0）→ 配置可信（P1）→ 研讨真实（P2）→ 产出真实（P3/P4）→ 可维护（P5）
3. 所有 HTTP/WS 契约先定义 Pydantic 模型并与前端类型逐字段对齐，禁止单边改接口
4. 配置集中管理；所有依赖配置的客户端按配置版本统一失效，杜绝"启动时快照"
5. 数据清洗默认非破坏性：先识别、展示影响、由用户确认后再应用，原始数据始终可追溯
6. 测试不后置：每阶段同步补充对应单测、契约测试和集成测试

---

## 三、P0：工程与契约基线（1 天）——先让项目可复现、可联调

### BE-0.1 补齐依赖并生成锁文件

在直接依赖清单中补全：

```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2
pydantic-settings>=2      # 缺失，core/config.py 在用
httpx>=0.27               # 缺失，endpoints/config.py 在用
pandas>=2
openai>=1
langchain>=0.3
langchain-openai>=0.2
langchain-community>=0.3
langchain-text-splitters>=0.3  # 缺失，services/rag.py 在用
langgraph>=0.2
chromadb>=0.5
pypdf>=4                  # 缺失，PyPDFLoader 需要
openpyxl>=3.1             # xlsx 读取
xlrd>=2                   # xls 读取
tiktoken>=0.7             # Chat/Embeddings token 预算预留估算
python-pptx>=1
python-multipart
python-dotenv
tavily-python
beautifulsoup4
playwright
```

- 上述 `>=` 仅表示兼容范围，不视为锁定；使用 `pip-tools`/`uv lock` 生成包含间接依赖精确版本的锁文件
- 验收：全新 venv 严格按锁文件安装后，`uvicorn backend.main:app` 启动无 ImportError；csv/xls/xlsx/pdf 四类文件均可读取

### BE-0.2 建立测试与静态检查基线

- 增加 `pytest`、`pytest-asyncio`、`httpx`，建立 `/api/health`、应用导入和关键 Pydantic 模型的冒烟测试
- 增加 Ruff（格式、未使用导入、异常处理等基础规则），测试和静态检查命令写入 README
- LLM、Tavily、ChromaDB 一律 mock，基线测试不依赖真实密钥和网络
- 验收：`pytest`、Ruff 全绿，后续每个 BE 任务必须同步补对应测试

### BE-0.3 CORS 收敛（修 B14 部分）

- `allow_origins` 从配置读取，开发默认 `["http://localhost:5173"]`；无 Cookie 鉴权时 `allow_credentials=False`
- 前端已走 vite proxy（FE-0.4），联调期也不依赖 CORS 放开
- 验收：dev 全流程无跨域报错

### BE-0.4 配置模板与启动固化

- 明确唯一配置文件为项目根目录 `.env`，代码使用绝对路径定位，不依赖当前工作目录；新增 `.env.example`（所有配置项 + 注释）
- `.env` 保持在 `.gitignore` 中，日志、错误响应和 API 永不输出完整密钥
- README 固化启动命令 `uvicorn backend.main:app --reload`（项目根目录）
- 验收：新同事按 README 5 分钟跑起

### BE-0.5 冻结前后端 API/WS 契约

- 为配置、选题对话、数据清洗检测/应用/撤销、图表生成/推荐、PPT 生成/下载、usage、研讨纪要定义明确的 Pydantic request/response model，统一错误结构：`{code, message, details?, request_id?}`
- `/topic/chat` 的 history 统一为结构化 `[{role, content}]`，禁止继续拼接自由格式字符串
- 数据上传响应统一为 `{dataset_id, revision, filename, columns, rows, report}`，清洗契约明确 `detect/apply/undo`、逐列决策和影响行；禁止 service 与 endpoint 重复包裹业务对象
- `discussion_summary` 统一为结构化对象：`{problem, root_causes, countermeasures, summary}`，PPT 接口直接接收该对象，不再由前端拼字符串
- PPT 生成响应统一为 `{file_id, display_name, expires_at}`，下载路由为 `/api/ppt/download/{file_id}`，不再把磁盘文件名暴露给前端
- usage 响应至少包含 `{budget_usd, known_cost_usd, remaining_usd, unknown_cost, usage_by_model}`
- WebSocket 线上字段统一使用 snake_case：客户端消息 `{type, session_id, client_message_id, last_event_seq?, topic?, data_summary?, content?}`；服务端事件 `{type, session_id, event_seq, timestamp, reply_to_client_message_id?, agent?, content?, summary?, round?, error?, recoverable?}`，`timestamp` 统一为 UTC ISO 8601
- `client_message_id` 仅用于客户端请求幂等；`event_seq` 为 session 内服务端单调递增重放游标，二者禁止混用
- 前端按该契约生成/维护 TypeScript 类型；契约变更必须同步更新 BE/FE 编号及测试
- 验收：OpenAPI 示例、WS 协议示例和前端类型逐字段一致，完成一次 mock 联调

---

## 四、P1：配置系统与预算基础（2 天，最高优先级，修 B1/B2/B3）

目标：**保存即生效，无需重启，重启不丢。**

### BE-1.1 单一配置源 + 持久化

改动 `core/config.py`：

- `Settings` 支持运行时更新；`/config/update` 不再裸写 `os.environ`，改为：
  1. 更新 `settings` 对象字段
  2. 用 `python-dotenv` 的 `set_key` 写回项目根目录 `.env` 持久化（路径由统一配置模块解析）
- `GET /config/` 改从 `settings` 读取（消灭双轨）
- 配置更新加进程内锁；写文件采用临时文件替换，避免并发写坏 `.env`
- CI 验收：使用 fake provider 验证保存后下一次 `/topic/chat` 使用新配置，重启测试应用后配置仍在；人工集成验收可另用真实 key 验证，不作为无密钥 CI 的门禁

### BE-1.2 配置版本与客户端统一失效机制

- 配置更新成功后递增 `config_revision`；新增工厂统一管理 `ChatOpenAI`、`OpenAIEmbeddings`、`TavilyClient`
- 缓存键至少包含配置版本、base URL、key 指纹、模型和本地/远程模式；密钥本身不得进入日志
- `topic_consultant`、`discussion`、`rag`、`search` 删除各自的启动时客户端缓存，均通过工厂获取当前版本资源
- 验收：依次更换 OpenAI Key、Base URL、Tavily Key 后，下一次调用均使用新配置；旧客户端不再被引用

### BE-1.3 契约对齐（与 FE-1.6 联调，修 B3）

- 字段统一为 `max_budget_usd`（前后端一致）
- `GET /config/` 返回：`has_openai_key`、`has_tavily_key`、其余非敏感字段明文；**永不返回完整密钥**
- `/update` 语义：密钥字段传空 = 不修改；传值 = 覆盖
- 配置状态统一为 `checking | ready | missing | degraded`，供前端路由守卫使用
- 验收：前端配置页回显正确、预算保存成功、密钥可更新不回显

### BE-1.4 连通性检查增强

- `/check-connectivity` 返回延迟 + 模型可用性；本地 Ollama 模式先 `GET /api/tags` 探测
- 验收：故意填错 key，返回结构化错误而非 500 堆栈
- 测试：配置读写、空密钥语义、敏感字段不泄露、三类客户端缓存失效全部覆盖

### BE-1.5 最小 usage 与预算账本

- 在 SQLite 建立 usage ledger；统一调用包装器支持调用前预算预留、调用后按实际 Chat/Embeddings usage 结算、失败释放预留额度
- `data/model_prices.json` 按供应商/模型记录输入、输出、缓存 token 和 embeddings 单价及生效日期；启用预算时，未知外部模型在调用前返回 `MODEL_PRICE_UNKNOWN`，不得以“费用未知”继续消耗；本地模型默认费用为 0
- P2 的轮次预算与 RAG embeddings 直接复用该账本，不另写临时计量逻辑
- 本阶段只提供内部 service；展示/审计 API 在 BE-5.2 完成
- 验收：并发 fake provider 调用不能突破预算；未知外部模型被拒绝，本地模型记 0，调用失败释放预留额度

---

## 五、P2：研讨真实化（2~3 天，修 B4/B5/B12，核心卖点）

### BE-2.1 五角色提示词落地

重写 `agents/discussion.py`，每个 agent 定义系统提示词并真实调用 LLM（走 BE-1.2 工厂）：

| 角色 | 职责 |
|---|---|
| moderator 主持人 | 控场、决定下一发言者、判断收敛 |
| researcher 研究员 | 检索知识库（RAG）与联网搜索，给背景资料 |
| analyst 数据分析师 | 结合清洗后数据分析问题 |
| critic 反方 | 质疑论证、查漏补缺 |
| writer 撰稿人 | 输出结构化研讨纪要 |

### BE-2.2 moderator 智能路由

- 下一发言者由 LLM 决策（输入：历史 + 各角色职责），替换数消息条数的硬编码状态机
- 路由输出使用枚举/结构化输出并校验；解析失败时走确定性兜底顺序
- `iteration_count`、累计 token、累计耗时均设上限，任一达到阈值即转 writer 收尾，防死循环与预算失控
- 验收：正常、路由解析失败、达到轮数/预算上限三种情况均能收敛到 writer；不以“每次顺序必须不同”作为正确性标准

### BE-2.3 WebSocket 会话保持（修 B5）

改动 `endpoints/discussion.py`：

- 使用 `session_id/thread_id` + SQLite durable inbox/outbox 保存命令、状态快照和事件，保证进程重启后 TTL 内可恢复；禁止把“复用同一个 graph 实例”误当成会话续跑
- 按 BE-0.5 协议处理 `start/message/resume/finish`，服务端返回 `agent_message/round_done/finished/error/ack`
- 每条客户端请求带唯一 `client_message_id`，服务端按 session 去重；每个服务端事件分配单调递增 `event_seq`
- 断线重连时客户端发送最后收到的 `last_event_seq`，服务端补发序号更大的事件；`reply_to_client_message_id` 仅用于请求/响应关联
- `start` 消息必须携带 topic 与 data summary；原始完整表格不通过 WS 重复传输
- 验收：同连接多轮可引用前文；主动断网后 event 不重复展示；服务重启后 pending command 能继续或明确失败，不永久丢失

### BE-2.4 RAG 基础修复 + researcher 工具接入

- RAG 改为首次调用时初始化；`TextLoader` 优先 UTF-8，失败后探测 GBK；临时文件用 `try/finally` 清理
- 检索链：先查 ChromaDB 知识库，再按配置决定是否调用 Tavily；无 Tavily key 时跳过联网并明示
- 检索结果作为 researcher 的上下文注入，不直接当发言
- 上传限制类型与大小，PDF/TXT 入库失败返回结构化错误；嵌入调用纳入预算统计
- 验收：上传中文 txt/pdf 后可检索；研讨中的 researcher 能引用命中文档；异常时临时文件无残留

### BE-2.5 PII 过滤接入（修 B12）

- 发送给外部 LLM 前统一过 `pii_redactor.redact`（本地 Ollama 模式可配置跳过）
- 不注册为 HTTP 中间件（会误伤文件上传）；在统一 LLM 调用包装器中对消息内容预处理，不能只在“返回 ChatOpenAI 实例”的工厂中声明过滤
- 验收：输入含手机号/身份证号的研讨，出站请求中对应内容被 `[PHONE]` 等替换

### BE-2.6 结构化研讨纪要

- writer 最终输出 BE-0.5 定义的 `DiscussionSummary`：`{"problem": "...", "root_causes": [...], "countermeasures": [...], "summary": "..."}`
- 通过 `finished.summary` 下发并由会话状态持久化；如另设 GET 接口，必须按 `session_id` 查询，禁止使用无会话的全局 summary
- 对不稳定模型使用结构化输出校验 + 一次修复重试；仍失败时返回保留原文的降级结构
- CI 验收：用强模型/小模型典型响应 fixture 覆盖结构化成功、修复成功和降级结构三条路径；真实模型仅作为可选人工集成验收
- 测试：WS 协议、消息去重、断线续传、轮数上限、PII、RAG 编码与临时文件清理全部覆盖

---

## 六、P3：数据与图表增强（1~2 天，修 B9/B10）

### BE-3.1 数据清洗增强 + 清洗报告

改动 `services/data_cleaning.py`：

- 默认只检测，不自动填补或删除：空行/合计行、缺失值、IQR 异常值、疑似数字/百分比格式均先生成建议
- 接口支持按列/行提交清洗决策：`keep | drop_rows | median | forward_fill | convert_number | convert_percent`；先调用 preview 返回影响行，用户确认后再 apply
- 同时保留 `raw_data`（或原文件引用）与 `cleaned_data`，任何处理均可撤销；禁止用异常标记字段污染业务列
- 返回 `{data, report}`，report 至少包含 `removed_rows`、`filled_cells`、`outliers_detected`、`type_conversions`、逐列规则和受影响行号
- 百分比转换同时保留显示格式/单位说明，避免 `15%` 与 `0.15` 被误解
- 验收：检测模式不改变任何原值；用户确认后报告数字与人工核对一致，可一键恢复原始数据

### BE-3.2 key 列不污染数据（修 B9 部分）

- 不再 `df['key']=...`；行标识通过独立 `row_id` 元数据返回，不混入可分析字段
- 验收：表格编辑可稳定定位行，图表 X/Y 轴下拉框中不出现 `key`/`row_id`

### BE-3.3 上传校验

- 限制：单文件 ≤ 10MB、仅 csv/xls/xlsx、行数 ≤ 5000、列数设置合理上限
- 上传时分块读取并累计大小，避免先 `await file.read()` 把超限文件完整载入内存
- CSV 优先 UTF-8/UTF-8-SIG，失败后探测 GBK；扩展名、Content-Type 与实际文件头交叉校验
- 超限返回 400 + 中文原因
- 验收：超限文件被明确拒绝，不产生 500

### BE-3.4 图表服务修复

改动 `services/chart.py`：

- y 值按已确认的数据类型转换；无法转换时不静默剔除，统一返回 422 `DATA_Y_NOT_NUMERIC`、row_ids 和处理建议
- 重复 x 值聚合（bar/pie 求和，line 取序）
- 聚合规则由接口参数明确，默认值在前端可见，不得悄悄改变统计口径
- 验收：脏数据生成图表不报错，数值正确

### BE-3.5 图表推荐接口

- 新增 `POST /api/visualization/recommend`：按数据特征（基数、是否时间序列、数值分布）返回推荐类型 + 理由；规则引擎即可，不必上 LLM
- 拦截器规则扩充：类别 >20 不推荐 pie、非数值 y 拦截等
- 验收：对接前端 FE-4.5"智能推荐"按钮
- 测试：检测不改原值、应用/撤销规则、编码回退、上传限额、数值转换和聚合口径全部覆盖

---

## 七、P4：PPT 真实化（1~2 天，修 B8/B11）

### BE-4.1 图表图片真正插入（对接 FE-1.4/FE-1.5）

- `chart_images` 接收 base64（前端传 dataURL 去前缀）→ 解码 → `add_picture` 插入独立"数据图表"页
- Pydantic 列表字段使用 `Field(default_factory=list)`；限制图片数量、单图解码后大小、总请求体积和允许的 PNG/JPEG 类型
- 图片尺寸按版心等比缩放
- 验收：PPT 中肉眼可见本次生成的图表；超限或非法 base64 返回明确的 400

### BE-4.2 QC 成果标准结构

- 模板改为中文，章节对齐 QC 小组活动程序（PDCA 简化版）：课题简介 → 现状与数据 → 原因分析（研讨纪要） → 对策与建议 → 数据图表 → 总结
- 原因、对策和结论直接消费 `DiscussionSummary` 结构化字段，不再解析前端拼接字符串
- 预留模板文件机制：`backend/templates/` 放 `.pptx` 母版，存在则用母版生成（本期可先空目录）
- 验收：输出 PPT 六页中文结构，无写死文案

### BE-4.3 路径与文件安全（修 B11）

- 对外使用不可猜测的 `file_id` 下载，显示文件名与磁盘文件名分离；`project_name` 仅用于下载显示名，并做字符白名单和长度限制
- 下载时用 `Path.resolve()` + `os.path.commonpath()` 校验目标位于 `generated_ppts`，禁止使用简单字符串前缀判断
- 文件名加 UUID/时间戳防覆盖；用 FastAPI lifespan 定期清理 7 天前文件，清理失败只告警不影响启动
- 验收：构造 `../../etc` 类文件名被拒绝
- 测试：结构化纪要映射、图片页、非法图片、文件 ID、目录穿越和过期清理全部覆盖

---

## 八、P5：可观测性与质量（1~2 天，修 B14）

### BE-5.1 日志体系

- `logging` 统一配置（控制台 + `backend/logs/app.log` 滚动文件），替换全部 `print`
- 为 HTTP 请求、WS 会话生成 `request_id/session_id`，关键节点记录 LLM 调用（仅模型、耗时、token，内容脱敏）、WS 生命周期、PPT 生成
- 密钥、完整提示词、原始表格和 PII 不进入日志；异常响应不直接返回第三方堆栈
- 验收：一次完整流程在日志中可完整追踪

### BE-5.2 usage 查询与预算审计增强（补 README 宣称功能）

- 在 BE-1.5 账本上补充按模型/日期/会话汇总、价格版本与审计字段；达到 `max_budget_usd` 时返回统一结构化错误
- 新增 `GET /api/config/usage` 供前端展示
- 验收：输入/输出/embedding 费用可追溯核算；usage 汇总与底层 ledger 一致；未知费用状态准确

### BE-5.3 测试收口

- `pytest` + `httpx`/`TestClient`：
  - 单测：`data_cleaning`（含报告数字）、`chart`（数值化/聚合/拦截）、PII 脱敏、文件名清洗
  - 集成：`/api/health`、`/config` 读写闭环、`/data/upload` 正常与超限分支、PPT 生成（断言文件存在且含图片页）
- 增加契约测试：OpenAPI response model 与前端共享示例一致；WS 消息覆盖 start/resume/finish/error
- 增加一条不访问真实外部服务的完整流程测试：配置 → 选题 → 数据 → 研讨 → 图表 → PPT
- LLM 相关一律 mock，不依赖真实 key
- 验收：`pytest` 全绿；核心 service 设覆盖率门槛，外部适配器重点覆盖异常分支

### BE-5.4 健康检查增强

- `/api/health` 返回：LLM 配置状态、ChromaDB 可用性、磁盘可写
- 验收：缺配置时返回 degraded 而非 ok

---

## 九、P6（可选，配合前端 P5，单独立项）

- SQLite + SQLModel 项目持久化：`projects` 表（id/topic/data_json/discussion_json/chart/created_at）
- 项目 CRUD + 恢复接口，供前端历史记录页使用
- WS 鉴权（如后续多用户化）

---

## 十、工期与里程碑

| 阶段 | 内容 | 工期 | 里程碑 |
|---|---|---|---|
| P0 | BE-0.1~0.5 | 1 天 | 环境可复现、测试基线与前后端契约冻结 |
| P1 | BE-1.1~1.5 | 2 天 | 配置即时生效并持久化，最小预算账本可用 |
| P2 | BE-2.1~2.6 | 2~3 天 | 研讨为真实多智能体、有会话、出结构化纪要 |
| P3 | BE-3.1~3.5 | 2 天 | 非破坏性清洗可确认/撤销，图表口径明确可推荐 |
| P4 | BE-4.1~4.3 | 1~2 天 | PPT 中文六页、含真实图表、路径安全 |
| P5 | BE-5.1~5.4 | 1~2 天 | 有追踪日志、有可核算预算保护、测试全绿 |

**合计约 2~3 周。** 与前端计划可并行：P0/P1 先行冻结契约、配置语义和预算账本，P2~P4 按垂直流程持续联调。

---

## 十一、总体验收清单

- [ ] 全新 venv 安装后一键启动，无 ImportError
- [ ] OpenAPI、WS 协议、后端模型与前端类型逐字段一致
- [ ] 前端改配置 → 保存 → 立即用新配置对话成功；重启后配置保留
- [ ] OpenAI、Embeddings、Tavily 客户端均在配置变更后立即失效重建
- [ ] 研讨室多轮对话有上下文，断线恢复 event 不重复展示、pending command 不永久丢失，agent 发言为 LLM 实时生成（日志可证），无"[模拟"字样
- [ ] 出站 LLM 请求中 PII 已脱敏
- [ ] 上传脏数据后检测阶段不改原值；确认清洗可撤销，报告数字准确，图表统计口径明确，PPT 含真实图表
- [ ] 文件名注入、路径穿越、超限上传均被明确拒绝
- [ ] `pytest`、Ruff 全绿；并发预算不超支，未知外部模型调用前被明确拒绝

---

## 十二、风险

1. **LangGraph 版本差异**：节点调用与 `astream` 事件结构受版本影响，必须在锁定版本上验证 start/resume/finish 全链路
2. **本地 Ollama 模型能力**：小模型可能无法稳定输出结构化 JSON；采用 schema 校验、一次修复重试和保留原文的降级结构
3. **ChromaDB 嵌入成本**：ingest 产生 embeddings 费用，必须与 Chat usage 使用同一预算账本
4. **清洗改变事实口径**：自动填补可能改变 QC 结论，因此默认仅检测，所有修改须经用户确认并可撤销
5. **前后端并行改契约的窗口期**：契约变更只能从 BE-0.5 的模型和示例发起，并与对应 FE 任务同批合并
6. **单机 MVP 边界**：本计划采用 SQLite durable inbox/outbox 和租约支持单机重启恢复，但不支持多实例跨主机消费同一 session；多实例部署需另行设计共享数据库和连接路由

---

## 十三、直接开发实施规格

本节是编码依据。前文负责说明“为什么、先做什么”，本节固定“文件放哪里、接口长什么样、如何验收”。实现中如需改变本节契约，必须同步修改前端类型、mock 和契约测试。

### 13.1 目标目录

```text
backend/
├── app/
│   ├── agents/                 discussion.py、topic_consultant.py
│   ├── api/endpoints/          config.py、topic.py、data.py、rag.py、search.py、discussion.py、visualization.py、ppt.py
│   ├── core/
│   │   ├── config.py           Settings、配置文件路径、配置更新锁
│   │   ├── clients.py          ChatOpenAI/Embeddings/Tavily 工厂及配置版本缓存
│   │   ├── llm_gateway.py      PII、预算预留、调用、usage 结算、统一异常
│   │   ├── errors.py           AppError 与 FastAPI exception handler
│   │   └── logging.py          日志、request_id/session_id
│   ├── models/                 common.py、config.py、topic.py、data.py、discussion.py、chart.py、ppt.py
│   ├── repositories/           dataset_repository.py、discussion_repository.py、ppt_repository.py、usage_repository.py
│   ├── services/               现有 service + discussion_session.py
│   └── middleware/             pii.py
├── data/runtime/               dataset_sessions.sqlite3、discussion.sqlite3、ppt.sqlite3、usage.sqlite3（均不提交 Git）
├── data/model_prices.json      受版本控制的模型单价表（不含密钥）
├── generated_ppts/             生成文件（不提交 Git）
├── templates/                  可选 PPT 母版
├── tests/
│   ├── unit/                   test_config.py、test_cleaning.py、test_chart.py、test_pii.py、test_usage.py
│   ├── integration/            test_config_api.py、test_data_api.py、test_ppt_api.py、test_ws.py
│   └── fixtures/               csv/xls/xlsx/pdf、LLM 响应 fixture
├── requirements.in
├── requirements-dev.in
└── requirements.lock
```

### 13.2 固定运行与依赖命令

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install pip-tools
pip-compile backend/requirements.in -o backend/requirements.lock
pip install -r backend/requirements.lock
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
pytest backend/tests -q
ruff check backend
```

- Python 基线固定为 3.11；依赖升级只能通过重新生成锁文件并跑全量测试
- 旧 `requirements.txt` 删除；README 与 CI 统一安装 `requirements.lock`，避免两套依赖入口
- `main.py` 使用 FastAPI lifespan 初始化目录、SQLite 表、日志和过期文件清理，不在 import 阶段访问外部服务

### 13.3 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | 空 | 永不通过 GET 接口返回 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容地址 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 选题与研讨默认模型 |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | RAG 嵌入模型 |
| `USE_LOCAL_LLM` | `false` | 本地模型开关 |
| `LOCAL_LLM_URL` | `http://localhost:11434/v1` | Ollama 兼容地址 |
| `LOCAL_LLM_MODEL` | `llama3` | 本地模型名 |
| `TAVILY_API_KEY` | 空 | 联网检索密钥 |
| `MAX_BUDGET_USD` | `5.0` | 外部模型预算上限 |
| `LLM_MAX_OUTPUT_TOKENS` | `2048` | 单次调用预算预留使用的最大输出 token |
| `CORS_ORIGINS` | `http://localhost:5173` | 逗号分隔白名单 |
| `DATASET_TTL_HOURS` | `24` | 临时数据集有效期 |
| `PPT_TTL_DAYS` | `7` | PPT 有效期 |

### 13.4 通用响应与错误

成功响应直接返回业务模型，不再额外包一层 `data`。错误统一为：

```json
{
  "code": "DATA_FILE_TOO_LARGE",
  "message": "文件不能超过 10MB",
  "details": {"limit_bytes": 10485760},
  "request_id": "req_xx"
}
```

固定错误码至少包括：`CONFIG_INVALID`、`LLM_NOT_CONFIGURED`、`LLM_CONNECT_FAILED`、`MODEL_PRICE_UNKNOWN`、`MODEL_OUTPUT_LIMIT_UNSUPPORTED`、`BUDGET_EXCEEDED`、`DATA_FILE_TOO_LARGE`、`DATA_FORMAT_UNSUPPORTED`、`DATA_REVISION_CONFLICT`、`DATA_Y_NOT_NUMERIC`、`WS_PROTOCOL_ERROR`、`SESSION_NOT_FOUND`、`PPT_IMAGE_INVALID`、`FILE_NOT_FOUND`、`INTERNAL_ERROR`。

### 13.5 HTTP 契约

| 方法与路径 | 请求 | 成功响应 |
|---|---|---|
| `GET /api/config/` | — | `ConfigView`：非敏感配置、两个 `has_*_key`、`status`、`config_revision` |
| `POST /api/config/update` | `ConfigUpdate`；空密钥表示不修改 | 更新后的 `ConfigView` |
| `POST /api/config/check-connectivity` | `{provider, base_url, api_key?, model}` | `{status, latency_ms, model, message}` |
| `GET /api/config/usage` | — | `{budget_usd, known_cost_usd, remaining_usd, unknown_cost, usage_by_model}` |
| `POST /api/topic/chat` | `{message, history:[{role,content}]}` | `{response}` |
| `POST /api/data/upload` | multipart `file` | `DatasetResponse` |
| `GET /api/data/{dataset_id}` | — | 当前 `DatasetResponse`；不存在/过期返回 `SESSION_NOT_FOUND` |
| `POST /api/data/preview` | `CleaningApplyRequest` | `CleaningPreviewResponse`；不写库、不增加 revision |
| `POST /api/data/apply` | `CleaningApplyRequest` | 新 revision 的 `DatasetResponse` |
| `POST /api/data/undo` | `{dataset_id, base_revision}` | 新 revision 的 `DatasetResponse`，内容恢复原始值 |
| `POST /api/data/confirm` | `{dataset_id, revision}` | `DatasetResponse`，`confirmed_revision=revision` |
| `POST /api/visualization/generate` | `ChartRequest` | `{option, processing}` 或统一错误 |
| `POST /api/visualization/recommend` | `{columns, sample_rows}` | `{chart_type, x_axis, y_axis, reason}` |
| `POST /api/ppt/generate` | `PPTRequest` | `{file_id, display_name, expires_at}` |
| `GET /api/ppt/download/{file_id}` | — | `FileResponse` |
| `POST /api/rag/ingest` | multipart txt/pdf | `{document_id, filename, chunks}` |
| `POST /api/rag/search` | `{query, k}` | `{results:[{content,metadata,score}]}` |

关键数据模型：

```python
class DataRow(BaseModel):
    row_id: str
    values: dict[str, Any]

class CleaningRule(BaseModel):
    action: Literal["keep", "drop_rows", "median", "forward_fill", "convert_number", "convert_percent"]
    column: str | None = None
    row_ids: list[str] = Field(default_factory=list)

class DatasetResponse(BaseModel):
    dataset_id: str
    revision: int
    confirmed_revision: int | None = None
    restored_from_revision: int | None = None
    filename: str
    columns: list[ColumnInfo]
    rows: list[DataRow]
    report: CleaningReport

class CleaningApplyRequest(BaseModel):
    dataset_id: str
    base_revision: int
    rules: list[CleaningRule]

class CleaningPreviewResponse(BaseModel):
    dataset_id: str
    base_revision: int
    preview_rows: list[DataRow]
    report: CleaningReport

class DiscussionSummary(BaseModel):
    problem: str
    root_causes: list[str]
    countermeasures: list[str]
    summary: str

class PPTRequest(BaseModel):
    project_name: str
    topic: str
    data_summary: str
    discussion_summary: DiscussionSummary
    chart_images: list[str] = Field(default_factory=list, max_length=5)
```

配置与基础模型：

```python
class ConfigView(BaseModel):
    openai_base_url: str
    openai_model: str
    use_local_llm: bool
    local_llm_url: str
    local_llm_model: str
    max_budget_usd: float
    has_openai_key: bool
    has_tavily_key: bool
    status: Literal["ready", "missing", "degraded"]
    config_revision: int

class ConfigUpdate(BaseModel):
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    use_local_llm: bool | None = None
    local_llm_url: str | None = None
    local_llm_model: str | None = None
    tavily_api_key: str | None = None
    max_budget_usd: float | None = Field(default=None, ge=0)

class TopicChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=50)

class PPTResult(BaseModel):
    file_id: UUID
    display_name: str
    expires_at: datetime
```

`ConfigUpdate` 中密钥为 `None` 或空字符串均表示“不修改”；本期不提供“清除密钥”操作，避免误清。确需清除时后续增加显式 `clear_openai_key/clear_tavily_key` 布尔字段，不复用空字符串。

usage 结构固定为：

```python
class ModelUsage(BaseModel):
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    known_cost_usd: Decimal

class UsageView(BaseModel):
    budget_usd: Decimal
    reserved_usd: Decimal
    known_cost_usd: Decimal
    remaining_usd: Decimal
    unknown_cost: bool
    usage_by_model: list[ModelUsage]
```

预算预留算法：从 `model_prices.json` 读取当前价格版本；Chat 输入 token 优先用 tiktoken 计算，无法识别编码时按 `ceil(字符数/2)` 保守估算；预留金额=`估算输入费用 + LLM_MAX_OUTPUT_TOKENS 对应输出费用 + safety_margin_usd`。Embeddings 按待嵌入文本估算 token 全额预留。每个外部 provider adapter 必须实现 `supports_output_limit` 并把统一上限映射到实际参数（如 `max_tokens/max_output_tokens`）；无法强制上限的 adapter 在预算开启时返回 `MODEL_OUTPUT_LIMIT_UNSUPPORTED`，不得调用。SQLite 使用 `BEGIN IMMEDIATE` 在同一事务中检查 `known_cost + reserved + 本次预留 <= budget` 并写 reservation；响应后按 provider usage 结算，多余预留释放，失败全部释放。价格未知时调用前返回 `MODEL_PRICE_UNKNOWN`。

usage 库使用 `reservations(id,request_id,provider,model,reserved_usd,status,created_at)` 和 `usage_events(id,request_id,provider,model,input_tokens,output_tokens,embedding_tokens,cost_usd,price_effective_from,created_at)`。若 provider 成功但不返回 usage，reservation 保持全额占用、标记 `status=usage_unknown`，`unknown_cost=true`，不释放额度。若 provider 报告的实际费用意外大于预留，则如实入账、标记 `status=provider_overrun` 并锁定后续外部调用，直到管理员提高预算或核对账目；因此“硬上限”验收以 provider 遵守强制输出上限为前提，异常 provider 只能做到立即熔断，不能撤销已经发生的第三方费用。

`model_prices.json` 每项包含 `{provider, model, input_per_1m, output_per_1m, cached_input_per_1m, embedding_per_1m, safety_margin_usd, currency, effective_from}`；价格更新新增生效记录，不覆盖旧记录，usage 行保存所用价格版本。CI 用 fake provider 验证其确实收到输出上限，并覆盖缺价格、不支持上限、缺 usage、actual overrun 四个分支。

其余模型字段固定如下：

```python
class ColumnInfo(BaseModel):
    name: str
    inferred_type: Literal["string", "number", "percent", "date", "boolean"]
    missing_count: int
    outlier_count: int
    display_format: Literal["plain", "percent", "date", "datetime"] = "plain"

class CleaningIssue(BaseModel):
    issue_type: Literal["empty_row", "total_row", "missing", "outlier", "type_conversion"]
    column: str | None = None
    row_ids: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)

class CleaningReport(BaseModel):
    mode: Literal["detected", "applied", "undone"]
    issues: list[CleaningIssue]
    applied_rules: list[CleaningRule] = Field(default_factory=list)
    removed_rows: int = 0
    filled_cells: int = 0
    outliers_detected: int = 0
    type_conversions: int = 0

class ChartRequest(BaseModel):
    chart_type: Literal["bar", "line", "pie"]
    dataset_id: str
    revision: int
    x_axis: str
    y_axis: str
    aggregation: Literal["none", "sum", "mean", "count"] | None = None

class ChartProcessing(BaseModel):
    aggregation: Literal["none", "sum", "mean", "count"]
    converted_row_ids: list[str] = Field(default_factory=list)
    grouped_categories: int = 0
    warnings: list[str] = Field(default_factory=list)

class ChartResponse(BaseModel):
    option: dict[str, Any]
    processing: ChartProcessing
```

`CleaningRule` 校验规则：`drop_rows` 必须提供非空 `row_ids`，可不填 column；`median/forward_fill/convert_*` 必须提供 column，row_ids 为空表示处理该列报告命中的全部问题行，非空则只处理指定行；`keep` 用于明确忽略报告项。preview 与 apply 调用同一个纯函数，apply 事务内重新检查 `base_revision` 后再写入。

`DataRow.values` 只允许 JSON-safe 标量：`null | string | boolean | finite number`，禁止直接返回 Pandas/Numpy/Decimal/datetime 对象。统一 `normalize_scalar()` 规则：`pd.NA/NaN/NaT`→null；正负 Infinity→null 并产生 issue；Numpy scalar 先 `.item()`；date→`YYYY-MM-DD`；无时区 datetime→ISO 8601 且不擅自加时区；Decimal/整数超出 JS 安全整数范围时转十进制字符串并产生精度提示；空字符串保持空字符串，不等同缺失；原始 `"15%"` 在检测阶段保持字符串且 column.display_format=percent，确认 `convert_percent` 后变为有限数值 `0.15`，前端按 display_format 显示为 15%。csv/xls/xlsx 共用该 normalization，三类 fixture 对同一逻辑表必须产生一致 rows。

revision 从 0 开始且只增不减。upload/apply/undo 后 `confirmed_revision=None`；confirm 仅在 revision 等于当前版本时写入 confirmed_revision。undo 将原始 rows 写成新版本 `revision=current+1`，并返回 `restored_from_revision=0`；任何旧 `base_revision` 均继续返回 409，禁止复用版本号。

图表只读取后端中与 `dataset_id+revision` 匹配且 `confirmed_revision=revision` 的数据，版本不一致或未确认返回 409。重复类别时默认规则：bar/pie=`sum`，line=`none` 并保留原行顺序；显式传 aggregation 时覆盖默认值。y 轴存在不可转换值时返回 422 `DATA_Y_NOT_NUMERIC` 和 row_ids，不静默忽略。

PPT 文件实际保存为 `generated_ppts/{file_id}.pptx`。`ppt_repository` 表结构为 `files(file_id,display_name,disk_path,created_at,expires_at)`；生成时先保存临时文件，成功后原子改名并写 metadata。下载只按 file_id 查询 metadata，再校验 resolved path；过期或记录不存在返回 `FILE_NOT_FOUND`。清理任务先删磁盘文件，再删 metadata；失败保留记录并写 warning，供下次重试。

- `dataset_repository` 使用表 `datasets(dataset_id PRIMARY KEY, filename, revision, confirmed_revision, raw_rows_json, current_rows_json, columns_json, report_json, created_at, expires_at)`；`apply` 必须在事务内校验 `base_revision`，冲突返回 409
- `CleaningReport` 同时包含检测项、已应用规则、受影响 row_id 和统计数量；upload 只检测，revision=0，不修改业务值
- 返回 5000 行用于当前桌面 MVP；如果响应实测超过 5MB，再单独增加分页，不在实现中临时改契约

### 13.6 WebSocket 契约与状态机

连接地址：`/api/discussion/ws`。第一条消息必须是 `start` 或 `resume`。

```json
{"type":"start","session_id":"s1","client_message_id":"c1","topic":"降低xx故障率","data_summary":"共xx行..."}
{"type":"message","session_id":"s1","client_message_id":"c2","content":"请继续分析"}
{"type":"resume","session_id":"s1","client_message_id":"c3","last_event_seq":6}
```

服务端事件统一带 `session_id`、单调递增 `event_seq`、UTC ISO 8601 `timestamp`：

```json
{"type":"agent_message","session_id":"s1","event_seq":1,"timestamp":"2026-xx-xxTxx:xx:xxZ","agent":"moderator","content":"..."}
{"type":"finished","session_id":"s1","event_seq":8,"timestamp":"2026-xx-xxTxx:xx:xxZ","summary":{"problem":"...","root_causes":[],"countermeasures":[],"summary":"..."}}
```

命令与状态转换固定如下：

| 当前状态 | 命令 | 服务端行为 |
|---|---|---|
| 不存在 | `start` | 事务创建 session 与 ack 事件，进入 running，随后产生 agent_message |
| running/round_done | `message` | 先落库 ack，再进入 running 执行下一轮 |
| running/round_done | `finish` | 先落库 ack，强制路由 writer，成功后落库 finished |
| created/running/round_done/finished/error | `resume` | 落库 ack 后重放 `event_seq > last_event_seq`；finished 只重放、不重新执行 |
| finished | `message/finish` | 返回不可恢复 `WS_PROTOCOL_ERROR` |
| error | `message/finish` | 返回不可恢复 `WS_PROTOCOL_ERROR`；客户端须新建 session |

`round_done` 事件必须带 `round`；`error` 事件必须带 `{error, recoverable}`。仅网络断开或可重试第三方超时标记 `recoverable=true`，session 状态回到 round_done，客户端可用新 `client_message_id` 重发；协议错误、预算耗尽和数据缺失为不可恢复 error。MVP 默认 SQLite durable inbox/outbox，保证进程重启后 24 小时内可恢复。

本期不依赖 LangGraph checkpointer承担传输可靠性；`discussion_repository` 自建 durable inbox/outbox：

- `sessions(session_id,status,state_json,next_event_seq,lease_owner,lease_generation,lease_until,expires_at)` 保存每个 agent 节点完成后的可恢复 AgentState；lease_generation 是 fencing token
- `commands(session_id,client_message_id,payload_json,status,picked_at,completed_at,error_json)`，status=`pending|running|completed|failed`
- `events(session_id,event_seq,client_message_id,event_type,payload_json,created_at)`
- `llm_operations(operation_id PRIMARY KEY,status,response_json,usage_id)`；operation_id=`session:client_message:agent:step`，已完成操作重试时直接复用 response_json

收到命令时事务插入 command(pending) 和 ack event；相同 client_message_id 返回既有 ack，不重复插入。每个 session 只能由一个 worker 持有数据库租约：领取时用 `BEGIN IMMEDIATE` 原子写 owner、`lease_generation=lease_generation+1`、`lease_until=now+30s`；worker 每 10s heartbeat 续租。第二连接可以订阅/重放，但不能执行命令。只有连续错过 heartbeat、lease_until 已过期时其他 worker才能领取，并获得更大的 generation。

worker 持有 `(lease_owner,lease_generation)` 后，从 pending 或租约过期的 running command 及 sessions.state_json 继续执行。所有 command/state/event 更新必须带 `WHERE session_id=? AND lease_owner=? AND lease_generation=? AND lease_until>now`；受影响行数为 0 表示已失租，旧 worker立即停止推进且不得发送事件。LLM 调用期间 heartbeat 独立运行；失租后即使旧调用返回，也只允许记录实际 usage/operation response，不得更新 session state。新 worker遇到同一 `llm_operations(operation_id)` 已 completed 时复用 response；仍 running 时最多等待 operation timeout，再按已记录规则重试并告警。每个节点完成后，在同一 SQLite 事务中更新 state_json、写 event、推进 event_seq；提交后才能发送。若崩溃发生在第三方已计费但响应未落库的极小窗口，可能重复调用，必须记录 warning 和独立 usage，不宣称外部调用 exactly-once。

该设计保证：已落库 command 不永久丢失；event 至少一次传输、前端按 event_seq 恰好一次展示；同一 session 命令严格串行。LangGraph仍用于节点/路由定义，但跨命令状态以 sessions.state_json 为权威；不再同时维护另一套无法原子协调的 SQLite checkpointer。

### 13.7 文件改动矩阵

| 任务 | 必改文件 | 同步测试 |
|---|---|---|
| BE-0.x | requirements、`main.py`、`models/*`、`core/errors.py` | `test_health.py`、契约 schema 快照 |
| BE-1.x | `core/config.py`、`core/clients.py`、`core/llm_gateway.py`、config endpoint、usage repository | config/usage 单测与 API 测试 |
| BE-2.x | `agents/discussion.py`、`services/discussion_session.py`、discussion endpoint、RAG/search | `test_ws.py`、`test_rag.py`、PII 测试 |
| BE-3.x | data/chart models、endpoints、services、dataset repository | cleaning/chart 单测与 data API 测试 |
| BE-4.x | PPT models、service、endpoint、templates | `test_ppt_api.py` |
| BE-5.x | logging、exception handler、health/usage endpoint | 完整流程集成测试 |

### 13.8 每个任务的完成定义

任务只有同时满足以下条件才可标记完成：代码和模型已实现；OpenAPI/WS 示例已更新；新增分支有测试；Ruff/pytest 全绿；日志无密钥和原始敏感数据；README 命令可执行；对应前端 mock/类型已同步。只完成 service、未接 endpoint 或未补测试，均不算完成。

### 13.9 建议提交顺序

1. `BE-0-contract-foundation`：依赖锁、目录、models、错误处理、测试基线
2. `BE-1-config-usage`：配置读写、客户端工厂、LLM gateway、预算账本
3. `BE-3-data-contract`：upload/apply/undo、dataset repository、图表接口（先于真实研讨联调）
4. `BE-2-discussion`：RAG、五角色、SQLite durable inbox/outbox、WS resume
5. `BE-4-ppt`：结构化纪要和图表图片进入 PPT、file_id 下载
6. `BE-5-observability`：日志、usage 查询、健康检查、完整流程测试

每个提交必须可独立启动和通过当时已有测试；禁止把模型/endpoint/service 分散到多个长期不可运行的提交。
