# 智能 QC 成果生成器 (Smart QC-Circle Generator)

## 项目简介

**智能 QC 成果生成器 (QCmaker)** 是一款基于大语言模型 (LLM) 和多智能体协作 (Multi-Agent) 技术的企业级应用，旨在辅助 QC 小组高效完成质量控制活动。该系统通过 AI 驱动的选题咨询、自动数据清洗、多模型研讨、智能可视化推荐以及 PPT 终稿生成，全流程赋能 QC 活动，显著降低参与门槛，提升成果质量。

## 核心功能

### 1. 系统配置 (System Configuration)
- **API 优先策略**：支持配置 OpenAI 兼容的 API Key (如 DeepSeek, Moonshot) 或本地 Ollama 模型地址。
- **成本控制**：内置 Token 消耗监控与预算保护机制（含预留/结算/超额熔断与一键复位）。
- **连通性检查**：一键测试 LLM 服务连通性。

### 安全机制（多层防护）
- **传输层**：安全响应头（nosniff / DENY / no-referrer / CSP）；CORS 白名单。
- **限流层**：每 IP 滑动窗口速率限制，超限返回 429。
- **鉴权层（可选）**：设置 `API_ACCESS_TOKEN` 后，所有 HTTP 接口需携带 `x-api-token` 头、WebSocket 需携带 `?token=`。
- **出站防护层**：模型 API 地址强制 http(s)、禁止内网/元数据地址（SSRF 防护）、禁止携带凭据。
- **数据脱敏层**：手机号/身份证/邮箱边界感知脱敏，同时作用于 LLM 输入与输出。
- **资金防护层**：预算预留-结算-对账闭环；预留泄漏自动回收；供应商超额熔断与管理复位；embedding 调用同样计费入账。

### 2. QC 选题顾问 (Topic Consultant)
- **AI 引导对话**：通过自然语言对话，辅助用户挖掘痛点，明确 QC 课题。
- **参考资料上传**：支持 Word(.docx) / Excel(.xlsx/.xls) / PPT(.pptx) / PDF / Markdown / CSV / TXT 上传入知识库，检索结果自动作为选题对话与 SMART 评估的参考依据。
- **选题评估**：基于 SMART 原则自动评估选题的可行性与价值。

### 3. 数据清洗与预览 (Data Cleaning & Review)
- **智能清洗**：自动处理缺失值、异常值，转换数据格式。
- **交互式预览**：提供类似 Excel 的在线编辑界面，支持手动微调数据。
- **文件支持**：支持 CSV、Excel 等常见数据格式上传。

### 4. 多模型研讨室 (Multi-Model Discussion Room)
- **多智能体协作**：集成多个 AI 角色（如数据分析师、质量专家、主持人），模拟专家研讨会。
- **根因分析**：通过头脑风暴和逻辑推理，深度挖掘问题根因。
- **会议纪要**：自动生成结构化的研讨总结。

### 5. 可视化与决策 (Visualization & Decision)
- **智能图表推荐**：根据数据特征自动推荐最合适的图表类型（柱状图、折线图、饼图等）。
- **ECharts 集成**：基于 ECharts 生成高质量、可交互的数据图表。
- **图表拦截器**：自动检测并拦截不合理的图表生成请求。

### 6. 终稿生成 (Final Draft Generation)
- **PPT 自动生成**：一键将研讨成果、数据图表生成为标准的 PPT 汇报文档。
- **模板管理**：支持自定义 PPT 模板（开发中）。
- **在线预览**：提供 PPT 生成结果的在线预览与下载。

## 技术栈

### 前端 (Frontend)
- **框架**: React 18 + Vite
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
- Node.js (v18+)
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
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
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
访问浏览器地址：`http://localhost:5173`

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
