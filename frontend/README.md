# QCmaker Frontend (智能 QC 成果生成器前端)

## 项目简介

这是 **智能 QC 成果生成器 (QCmaker)** 的前端项目，基于 **React 18** 和 **Vite** 构建。它提供了一个现代化的、响应式的用户界面，用于引导用户完成 QC 活动的各个阶段，包括系统配置、选题咨询、数据清洗、多模型研讨、可视化决策和 PPT 预览。

前端采用 **Ant Design** 组件库和 **Tailwind CSS** 进行样式开发，并集成 **ECharts** 进行数据可视化。

## 核心功能模块

### 1. 系统配置 (ConfigPanel)
- 配置 API Key (OpenAI/DeepSeek/Moonshot) 或本地 Ollama 地址。
- 检查后端连通性。

### 2. 选题顾问 (TopicChat)
- 与 AI 顾问进行自然语言对话，确定 QC 课题。
- 确认选题后自动流转到下一阶段。

### 3. 数据清洗 (DataReview)
- 上传 CSV/Excel 数据文件。
- 预览并手动编辑清洗后的数据。

### 4. 研讨室 (DiscussionRoom)
- 实时展示多智能体研讨过程 (WebSocket)。
- 用户可随时介入对话。

### 5. 可视化 (VisualizationPanel)
- 根据数据生成 ECharts 图表。
- 支持切换图表类型 (柱状图/折线图/饼图)。

### 6. PPT 预览 (PPTPreview)
- 请求后端生成 PPT。
- 提供下载链接。

## 技术栈

- **构建工具**: Vite
- **框架**: React 18
- **UI 库**: Ant Design (AntD)
- **样式**: Tailwind CSS
- **图表**: ECharts, echarts-for-react
- **HTTP 请求**: Axios
- **图标**: @ant-design/icons

## 开发指南

### 1. 安装依赖

```bash
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

访问 `http://localhost:5173`。

### 3. 构建生产版本

```bash
npm run build
```

构建产物将输出到 `dist` 目录。

### 4. 代码规范

项目配置了 ESLint 进行代码检查。

```bash
npm run lint
```

## 目录结构

```
frontend/
├── src/
│   ├── api/            # Axios 客户端封装
│   ├── components/     # React 组件
│   │   ├── ConfigPanel.jsx
│   │   ├── TopicChat.jsx
│   │   ├── DataReview.jsx
│   │   ├── DiscussionRoom.jsx
│   │   ├── VisualizationPanel.jsx
│   │   └── PPTPreview.jsx
│   ├── App.jsx         # 主应用组件
│   ├── main.tsx        # 入口文件
│   └── index.css       # 全局样式 (Tailwind)
├── public/             # 静态资源
├── package.json        # 依赖配置
├── vite.config.ts      # Vite 配置
└── README.md           # 前端文档
```

## 贡献指南

请确保代码风格一致，并在提交前运行 Lint 检查。

## 许可证

MIT License
