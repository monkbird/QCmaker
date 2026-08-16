# QCmaker 前端

基于 React、TypeScript、Vite、Ant Design 与 ECharts 的六步式 QC 成果工作台。接口字段、路由门禁和持久化行为与 `docs/frontend-dev-plan.md`、`docs/backend-dev-plan.md` 保持一致。

## 本地运行

```bash
npm install
npm run dev
```

开发代理由 `.env.development` 中的 `VITE_DEV_API_TARGET` 配置。生产环境通过 `VITE_API_BASE_URL` 和可选的 `VITE_WS_BASE_URL` 指定服务地址，业务源码不写死主机名。

## 质量检查

```bash
npm run lint
npm run test
npm run build
npm run test:e2e
```

## 主要目录

```text
src/
├── api/          # HTTP 客户端、错误归一化与各领域接口
├── components/   # 通用步骤、头像、图标按钮和错误边界
├── context/      # 向导状态、reducer、恢复与持久化
├── hooks/        # 路由门禁、WebSocket 续传与重连
├── layouts/      # 六步工作台布局
├── pages/        # 配置、选题、数据、研讨、图表、PPT 页面
├── storage/      # IndexedDB schema 与读写封装
├── test/         # Vitest 单元测试
└── types/        # 与后端 wire format 对齐的类型
```

浏览器会保存项目状态、原始数据文件、研讨事件和图表图片。刷新时先校验后端数据集；数据集过期且本地仍有原文件时会尝试重新上传。清空项目会同时清理四个 IndexedDB store。

## 交互规范

- 短文字操作保持紧凑，默认按钮高 32px，主操作高 36px。
- 仅图标操作必须包含 Tooltip 和 `aria-label`，点击区不小于 32×32px。
- 数据修改必须先预览影响范围，再应用；下游成果按数据 revision 自动失效。
- PPT 下载只使用后端返回的不可猜测 `file_id`。

## 模型服务

配置页按国内、国际、本地和自定义四组展示模型服务商。填写 API Key 后点击模型名称输入框，会通过 `/api/config/models` 直接获取该账户在厂商接口中真实可用的模型；前后端均不保存静态模型名单。缺少密钥或厂商接口失败时明确提示，同时保留手工输入模型 ID 的能力。切换云端服务商必须同时填写新服务商的 API Key，避免误用上一家服务商的密钥。
