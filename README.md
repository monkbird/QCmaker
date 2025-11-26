# 智能 QC 成果生成器 (Smart QC-Circle Generator)

## 项目简介

**智能 QC 成果生成器 (QCmaker)** 是一款基于大语言模型 (LLM) 和多智能体协作 (Multi-Agent) 技术的企业级应用，旨在辅助 QC 小组高效完成质量控制活动。该系统通过 AI 驱动的选题咨询、自动数据清洗、多模型研讨、智能可视化推荐以及 PPT 终稿生成，全流程赋能 QC 活动，显著降低参与门槛，提升成果质量。

## 核心功能

### 1. 系统配置 (System Configuration)
- **API 优先策略**：支持配置 OpenAI 兼容的 API Key (如 DeepSeek, Moonshot) 或本地 Ollama 模型地址。
- **成本控制**：内置 Token 消耗监控与预算保护机制。
- **连通性检查**：一键测试 LLM 服务连通性。

### 2. QC 选题顾问 (Topic Consultant)
- **AI 引导对话**：通过自然语言对话，辅助用户挖掘痛点，明确 QC 课题。
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
- Python (v3.10+)

### 1. 后端启动
进入 `backend` 目录并安装依赖：
```bash
cd backend
pip install -r requirements.txt
```
启动后端服务（在项目根目录下运行）：
```bash
# 回退到项目根目录
cd ..
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
│   │   │   ├── discussion.py       # 多智能体研讨编排
│   │   │   └── topic_consultant.py # 选题顾问智能体
│   │   ├── api/
│   │   │   └── endpoints/
│   │   │       ├── config.py       # 配置接口
│   │   │       ├── data.py         # 数据处理接口
│   │   │       ├── discussion.py   # 研讨接口 (WebSocket)
│   │   │       ├── ppt.py          # PPT 生成接口
│   │   │       ├── rag.py          # RAG 检索接口
│   │   │       ├── search.py       # 搜索接口
│   │   │       ├── topic.py        # 选题接口
│   │   │       └── visualization.py# 可视化接口
│   │   ├── core/
│   │   │   └── config.py           # 核心配置
│   │   ├── middleware/
│   │   │   └── pii.py              # PII 敏感信息过滤
│   │   └── services/
│   │       ├── chart.py            # 图表生成服务
│   │       ├── data_cleaning.py    # 数据清洗服务
│   │       ├── ppt.py              # PPT 生成服务
│   │       ├── rag.py              # RAG 服务
│   │       └── search.py           # 搜索服务
│   ├── data/                       # 本地数据存储
│   ├── main.py                     # 后端入口
│   ├── requirements.txt            # Python 依赖
│   └── README.md                   # 后端文档
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.js           # Axios 客户端
│   │   ├── components/
│   │   │   ├── ConfigPanel.jsx     # 系统配置面板
│   │   │   ├── DataReview.jsx      # 数据清洗预览
│   │   │   ├── DiscussionRoom.jsx  # 研讨室
│   │   │   ├── PPTPreview.jsx      # PPT 预览
│   │   │   ├── TopicChat.jsx       # 选题顾问聊天
│   │   │   └── VisualizationPanel.jsx # 可视化面板
│   │   ├── App.jsx                 # 主应用组件
│   │   ├── main.tsx                # 前端入口
│   │   └── index.css               # 全局样式
│   ├── index.html
│   ├── package.json                # npm 依赖
│   ├── postcss.config.js
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   └── README.md                   # 前端文档
└── README.md                       # 项目主文档
```

## 贡献指南
欢迎提交 Issue 和 Pull Request 来改进本项目。

## 许可证
MIT License
