# QCmaker Backend (智能 QC 成果生成器后端)

## 项目简介

这是 **智能 QC 成果生成器 (QCmaker)** 的后端服务，基于 **FastAPI** 框架构建。它提供了全套的 AI 驱动服务，包括大模型对话管理、RAG (检索增强生成) 知识库、数据清洗与分析、图表生成建议以及最终的 PPT 报告生成。

后端采用模块化设计，利用 **LangChain** 和 **LangGraph** 编排复杂的多智能体协作流程，并集成 **ChromaDB** 作为向量数据库支持本地知识检索。

## 核心功能模块

### 1. 智能体服务 (Agents)
- **Topic Consultant**: 选题顾问智能体，辅助用户进行 QC 课题挖掘和评估。
- **Discussion Orchestrator**: 基于 LangGraph 的多智能体研讨编排器，协调主持人、数据分析师、质量专家等角色进行头脑风暴。

### 2. 知识检索 (RAG & Search)
- **RAG System**: 基于 ChromaDB 的本地知识库，支持上传文档并进行语义检索。
- **Web Search**: 集成 Tavily/Google Search API，为智能体提供实时网络信息补充。
- **PII Redaction**: 内置敏感信息过滤中间件，保护用户数据隐私。

### 3. 数据处理 (Data Processing)
- **Data Cleaning**: 基于 Pandas 的自动化数据清洗管道，处理缺失值、异常值。
- **Chart Generation**: 智能分析数据特征，生成 ECharts 配置代码 (JSON)。

### 4. 文档生成 (Document Generation)
- **PPT Engine**: 使用 `python-pptx` 库，将研讨内容和图表自动排版生成 PowerPoint 演示文稿。

## 技术栈

- **Web 框架**: FastAPI
- **语言**: Python 3.10+
- **LLM 编排**: LangChain, LangGraph
- **向量数据库**: ChromaDB
- **数据分析**: Pandas, NumPy
- **PPT 生成**: python-pptx
- **搜索服务**: Tavily API / Google Custom Search
- **API 客户端**: OpenAI SDK (兼容 DeepSeek, Moonshot, Ollama)

## 安装与运行

### 1. 环境准备
确保已安装 Python 3.10 或更高版本。建议使用虚拟环境。

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境 (Windows)
.\venv\Scripts\activate

# 激活虚拟环境 (Linux/macOS)
source venv/bin/activate
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
项目支持通过 API 动态配置，也支持 `.env` 文件。
在 `backend` 目录下创建 `.env` 文件（可选）：

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
TAVILY_API_KEY=your_tavily_key
```

### 4. 启动服务
在项目根目录下运行：

```bash
# 开发模式 (支持热重载)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

服务启动后，API 文档地址：
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 目录结构

```
backend/
├── app/
│   ├── agents/         # 智能体定义 (LangGraph, LangChain)
│   ├── api/            # API 路由 (Endpoints)
│   ├── core/           # 核心配置 (Config, Logging)
│   ├── models/         # Pydantic 数据模型
│   ├── services/       # 业务逻辑服务 (PPT, RAG, Data)
│   └── middleware/     # 中间件 (PII 过滤)
├── data/               # 本地数据存储 (ChromaDB, Uploads)
├── main.py             # 应用入口
└── requirements.txt    # 依赖列表
```

## API 概览

- `/config`: 系统配置管理
- `/topic`: 选题咨询对话
- `/data`: 数据上传与清洗
- `/rag`: 知识库管理与检索
- `/discussion`: 多智能体研讨 (WebSocket)
- `/visualization`: 图表生成建议
- `/ppt`: PPT 生成与下载

## 贡献指南

请遵循 PEP 8 编码规范。提交代码前请确保通过所有单元测试。

## 许可证

MIT License
