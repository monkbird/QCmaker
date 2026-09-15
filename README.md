# 智能 QC 成果生成器 (Smart QC-Circle Generator)

## 项目简介

**智能 QC 成果生成器 (QCmaker)** 是一款基于大语言模型 (LLM) 和多智能体协作 (Multi-Agent) 技术的企业级应用，旨在辅助 QC 小组高效完成质量控制活动。该系统通过 AI 驱动的选题咨询、自动数据清洗、多模型研讨、智能可视化推荐以及 PPT 终稿生成，全流程赋能 QC 活动，显著降低参与门槛，提升成果质量。

## 核心功能

### 管理控制台

管理入口为 `/admin`，使用独立的管理员账号、Cookie 会话与 CSRF 校验。首次启用、HTTPS 同源代理、密码恢复、令牌轮换及数据备份步骤见 [管理控制台运维说明](docs/admin-console-operations.md)。默认关闭管理入口，设置 `ADMIN_ENABLED=true` 并完成首次账号初始化后使用。管理审计覆盖管理接口，遗留业务入口仍沿用业务访问令牌。

### 1. 系统配置 (System Configuration)
- **API 优先策略**：支持配置 OpenAI 兼容的 API Key（如 DeepSeek、Moonshot）或本地 Ollama 模型地址；模型地址变更时需填写对应凭据。
- **成本控制**：内置 Token 消耗监控与预算保护机制（含预留/结算/超额熔断与一键复位）。
- **连通性检查**：一键测试 LLM 服务连通性。

### 安全机制（多层防护）
- **传输层**：安全响应头（nosniff / DENY / no-referrer / CSP）；CORS 白名单。
- **限流层**：HTTP 与 WebSocket 分别按可信客户端地址限流；不直接信任请求自带的 X-Forwarded-For。
- **业务鉴权层（可选）**：设置 `API_ACCESS_TOKEN` 后，业务 HTTP 接口需携带 `x-api-token` 头、WebSocket 需携带 `?token=`；管理接口独立验证管理员会话。
- **出站防护层**：模型 API 地址强制 http(s)、禁止内网/元数据地址（SSRF 防护）、禁止携带凭据。
- **数据脱敏层**：手机号/身份证/邮箱边界感知脱敏，作用于聊天输入/输出及 embedding 文档/查询输入。原文仍保留在本地数据存储中。
- **资金防护层**：预算预留-结算-对账闭环；未发出请求的预留泄漏自动回收；已发出但费用未知的请求持续占用预算，需对账；供应商超额熔断与管理复位；文档与查询 embedding 均计费入账。

### 2. QC 选题顾问 (Topic Consultant)
- **AI 引导对话**：通过自然语言对话，辅助用户挖掘痛点，明确 QC 课题。
- **参考资料上传**：支持 Word(.docx) / Excel(.xlsx/.xls) / PPT(.pptx) / PDF / Markdown / CSV / TXT 上传入知识库，检索结果自动作为选题对话与 SMART 评估的参考依据。
- **选题评估**：基于 SMART 原则自动评估选题的可行性与价值。

### 3. 数据清洗与预览 (Data Cleaning & Review)
- **智能清洗**：检测缺失值、异常值及格式问题，按用户确认的规则处理；异常值默认保留。
- **交互式预览**：分页查看全部数据，选择处理规则，预览与应用保持一致；暂不支持任意单元格编辑。
- **文件支持**：支持 CSV、Excel 等常见数据格式上传。

### 4. 多模型研讨室 (Multi-Model Discussion Room)
- **多智能体协作**：集成多个 AI 角色（如数据分析师、质量专家、主持人），模拟专家研讨会。
- **根因分析**：通过头脑风暴和逻辑推理，结合已确认数据版本的统计与样本分析问题，结果仍需业务人员核验。
- **会议纪要**：自动生成结构化的研讨总结。

### 5. 可视化与决策 (Visualization & Decision)
- **智能图表推荐**：根据数据特征自动推荐最合适的图表类型（柱状图、折线图、饼图等）。
- **ECharts 集成**：基于 ECharts 生成高质量、可交互的数据图表。
- **图表拦截器**：自动检测并拦截不合理的图表生成请求。

### 6. 终稿生成 (Final Draft Generation)
- **PPT 自动生成**：一键将研讨成果、数据图表生成为标准的 PPT 汇报文档。
- **模板管理**：可在 backend/templates 中放置本地 PPT 模板；尚无在线模板管理界面。
- **在线预览**：提供成果结构示意和带鉴权下载；不提供生成文件的在线逐页渲染，长内容和多图自动分页。

## 技术栈

### 前端 (Frontend)
- **框架**: React 19 + Vite
- **UI 组件库**: Ant Design (AntD)
- **样式**: Tailwind CSS
- **图表**: ECharts (echarts-for-react)
- **HTTP 客户端**: Axios

### 后端 (Backend)
- **框架**: FastAPI
- **AI 编排**: LangChain, LangGraph
- **向量数据库**: ChromaDB
- **数据处理**: Pandas
- **PPT 生成**: python-pptx

## 安装与运行

### 前置要求
- Node.js（20.19+ 或 22.12+）
- Python 3.11

### 1. 后端启动
在项目根目录创建虚拟环境并按锁文件安装：
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.lock
```
启动后端服务（在项目根目录下运行）：
```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. 前端启动
进入 `frontend` 目录并安装依赖：
```bash
cd frontend
npm install
```
启动前端开发服务器：
```bash
npm run dev
```
开发环境需要在 `frontend/.env.development` 配置 `VITE_DEV_API_TARGET=http://127.0.0.1:8000`。访问浏览器地址：`http://localhost:5173`。

## 项目结构

```
QCmaker/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   └── discussion.py       # 多智能体角色图 (LangGraph)
│   │   ├── api/endpoints/          # config / data / discussion(WS) / ppt / rag / search / topic / visualization
│   │   ├── core/
│   │   │   ├── clients.py          # LLM/Embedding 客户端缓存
│   │   │   ├── config.py           # 配置与 .env 原子更新（键校验）
│   │   │   ├── errors.py           # 统一错误与 request_id
│   │   │   ├── llm_gateway.py      # 预算预留 + PII 脱敏网关
│   │   │   └── security.py         # 限流 / 安全头 / 访问令牌 / SSRF 防护
│   │   ├── middleware/pii.py       # PII 脱敏（边界感知）
│   │   ├── models/contracts.py     # Pydantic 契约
│   │   ├── repositories/           # SQLite 数据访问
│   │   └── services/               # chart / data_cleaning / discussion_session / maintenance / model_providers / ppt / rag / search / usage
│   ├── tests/                      # pytest 回归测试（离线隔离）
│   ├── main.py                     # 后端入口
│   └── requirements.in / requirements.lock
├── frontend/
│   ├── src/
│   │   ├── api/                    # axios 客户端（支持 VITE_API_TOKEN）
│   │   ├── context/                # 向导状态机 (reducer + 持久化)
│   │   ├── hooks/                  # useDiscussionSocket / useWizardGuard
│   │   ├── pages/                  # Config / Topic / Data / Discussion / Visualization / PPT
│   │   └── storage/db.ts           # IndexedDB 持久化（项目会话事件可清理）
│   └── package.json
└── README.md
```

## 贡献指南
欢迎提交 Issue 和 Pull Request 来改进本项目。

## 许可证
MIT License

## 修复与运行边界

- 研讨 start 必须提供 `project_id`、`dataset_id`、`revision`，后端核验已确认版本并生成统计/样本上下文。
- 知识库上传、检索、列表及删除按 `project_id` 过滤，换 API Key 不更换向量空间。历史无项目归属的资料被保留并隔离，需重新上传到明确项目后才能用于项目检索。
- 修改课题或数据后，下游成果及持久快照同时失效；旧版分散存储不能证明成果来源时会清空旧成果，数据和原文件保留。
- 默认只监听本机。网络共享部署须设置 `API_ACCESS_TOKEN` 并配置受信代理；当前是单个可信使用者/团队共享令牌模型，没有多租户权限管理。
- 模型出站禁用环境代理与自动重定向，每次 TCP 连接核验并绑定公网 IP；本地模型按显式本地地址访问。
- CSV/Excel 限制上传 10MB、5000 行、200 列及 Excel 解压体积 40MB；解析在线程池并发受限，不使用可强制终止的独立进程。
- `npm run test:e2e` 使用 `.env.test` 的离线测试令牌构建，测试后发布请重新执行 `npm run build`，不要发布测试构建。
