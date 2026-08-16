# QCmaker 前端详细开发计划

> 版本：v1.2 ｜ 依据：已通读 `frontend/src` 全部源码（6 个组件 + 入口 + api 层）
> 配套文档：《后端详细开发计划》（`backend-dev-plan.md`），任务编号 FE-x / BE-x 互相引用

---

## 一、现状结论（已核实）

| 维度 | 实际情况 |
|---|---|
| 技术栈 | React 19 + TypeScript + Vite 7 + Ant Design 6 + Tailwind CSS 4 + ECharts 6，无需升级 |
| 应用形态 | 单页六步向导：配置 → 选题 → 数据清洗 → 研讨(WS) → 可视化 → PPT |
| 步骤驱动 | `App.jsx` 用 `useState` 条件渲染，无路由、无持久化 |
| 代码规模 | 6 个组件约 800 行，JSX/TSX 混用 |

### 问题清单（按严重级）

| 级别 | 编号 | 问题 | 证据 |
|---|---|---|---|
| 🔴 | F1 | PPT 生成用写死的 mock 数据，真实选题/研讨/图表均未传入 | `PPTPreview.jsx` L16-22 |
| 🔴 | F2 | "确认选题"传的是输入框草稿；`handleTopicSelected` 只 console.log 未存储 | `TopicChat.jsx` L98、`App.jsx` L22 |
| 🔴 | F3 | 前后端配置契约断裂：前端表单字段 `max_budget`，后端要 `max_budget_usd`；前端回显读 `openai_api_key`，后端只返回 `has_openai_key`（预算保存静默失败、密钥永远回显空白） | `ConfigPanel.jsx` L19-26、`backend/app/api/endpoints/config.py` |
| 🔴 | F4 | 无路由无持久化：刷新丢全部进度、无法回退上一步 | `App.jsx` 全文 |
| 🟡 | F5 | API 地址三处硬编码 `localhost:8000`（axios / WebSocket / PPT 下载链接），无 proxy 无环境变量 | `client.js` L4、`DiscussionRoom.jsx` L24、`PPTPreview.jsx` L28 |
| 🟡 | F6 | 死代码：Vite 模板 `App.tsx`、`App.css`、`react.svg` 残留；`main.tsx` 引 `App.jsx`，`tsc -b` 检查不到业务代码 | `main.tsx` L4 |
| 🟡 | F7 | Tailwind v4 依赖 + v3 语法 `@tailwind base` 三件套 | `index.css` |
| 🟢 | F8 | WebSocket 无重连无错误提示；无错误边界；loading/empty/error 无规范 | `DiscussionRoom.jsx` L23-54 |
| 🟢 | F9 | 研讨消息只在组件内存，切走即丢 | `DiscussionRoom.jsx` L17 |
| 🟡 | F10 | 若直接把最多 5000 行数据和图表 base64 写入 `sessionStorage`，存在容量超限与频繁同步序列化卡顿风险 | 计划中的状态持久化方案 |

**核心判断**：最痛的不是界面陈旧，而是「产出是假的（F1/F2）+ 状态脆弱（F4）+ 配置存不上（F3）」。UI 美化排在这之后。

---

## 二、改造原则

1. 不动技术栈，不引入新 UI 库
2. 不引入 Redux/Zustand 等状态库——六步向导共享状态用一个 Context 足够
3. 顺序：先正确性（P1），再架构（P2），后美化（P3/P4）
4. 每阶段均可用冻结契约和 mock 独立验证；依赖后端后续阶段的真实联调另设门禁，不把未就绪依赖算作前端阶段失败
5. 界面坚持紧凑、精致：按钮宽度随内容自适应，杜绝短文字配大面积留白；常见轻操作优先采用图标按钮
6. HTTP/WS 字段以 BE-0.5 冻结契约为唯一依据，TypeScript 类型、mock 和测试同步更新
7. 轻状态与大数据分层保存，上游数据变化必须主动失效下游成果，禁止新旧流程数据混用
8. 测试随任务实施，不把 Context、路由守卫、WS 恢复和 PPT payload 测试推迟到收尾阶段

---

## 三、P0：工程基础修复（0.5~1 天）

### FE-0.1 清除死代码

- 先执行 `npm ci`，记录现状 `npm run build`/`npm run lint` 结果；当前未安装 `node_modules` 时不能把命令失败误判为源码失败
- 删除：`src/App.tsx`（Vite counter 模板）、`src/App.css`、`src/assets/react.svg`
- 检查 `index.html`、`public/` 中 `vite.svg` 引用并一并处理
- 验收：全仓 grep 无残留引用；`npm run dev` 启动正常

### FE-0.2 全量 TypeScript 化

改动文件：

| 原文件 | 目标 |
|---|---|
| `src/api/client.js` | `client.ts` |
| `src/App.jsx` | `App.tsx` |
| `src/components/*.jsx`（6 个） | 全部 `.tsx` |

新建 `src/types/index.ts`，定义：

```ts
interface QCConfig { openai_base_url?: string; use_local_llm: boolean; local_llm_url: string; max_budget_usd: number; has_openai_key?: boolean; has_tavily_key?: boolean }
interface ChatMessage { role: 'user' | 'assistant'; content: string }
interface DataRow { row_id: string; values: Record<string, unknown> }
interface DiscussionSummary { problem: string; root_causes: string[]; countermeasures: string[]; summary: string }
interface DiscussionCommand { type: string; session_id: string; client_message_id: string; last_event_seq?: number; topic?: string; data_summary?: string; content?: string }
interface DiscussionEvent { type: string; session_id: string; event_seq: number; reply_to_client_message_id?: string; agent?: string; content?: string; summary?: DiscussionSummary; round?: number; recoverable?: boolean; error?: AppError; timestamp: string }
type ChartOption = import('echarts').EChartsOption
```

- API 类型按 BE-0.5 的 OpenAPI/WS 示例生成或人工维护，禁止用 `[k: string]: unknown` 掩盖核心字段错误
- 每个组件补 Props interface（回调签名一并类型化）
- 验收：`npm run build`（含 `tsc -b`）零 error

### FE-0.3 Tailwind v4 语法迁移

- `src/index.css` 三行改为单行 `@import "tailwindcss";`
- 删除 `tailwind.config.js`；`postcss.config.js` 移除 `autoprefixer`；`npm uninstall autoprefixer`
- 逐页面肉眼回归（v3→v4 默认值有差异，重点看 Card 间距、表单、表格边框）
- 验收：构建通过，六步页面样式无肉眼可见退化

### FE-0.4 API 地址治理

- `vite.config.ts` 增加：

```ts
const env = loadEnv(mode, process.cwd(), '')
server: { proxy: { '/api': { target: env.VITE_DEV_API_TARGET, changeOrigin: true, ws: true } } }
```

- `client.ts`：`baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api'`
- HTTP 与 WS 使用同一地址策略：优先读取 `VITE_API_BASE_URL`，将 `http/https` 转换为 `ws/wss`；必要时允许 `VITE_WS_BASE_URL` 显式覆盖，不能只从 `window.location` 推导
- `PPTPreview`：读取生成响应中的 `file_id/display_name/expires_at`，下载链接使用 `/api/ppt/download/${file_id}`，不再依赖后端磁盘文件名
- 新增 `.env.development`（其中可配置 `VITE_DEV_API_TARGET=http://localhost:8000`）、`.env.example`；`src/vite-env.d.ts` 声明 env 类型
- 验收：dev 下无 CORS 报错；构建产物在非 8000 端口后端下仅需改 env

### FE-0.5 axios 响应拦截器

- `client.ts` 的 response 拦截器只把后端统一错误转换为 `AppError`，不直接调用 AntD 静态 `message`，避免 API 层耦合 UI 和重复弹窗
- 页面或统一错误展示层根据操作上下文决定 `Alert`、表单错误或 message；同一失败只展示一次
- 验收：人为断网触发一次失败，页面只弹一次错误提示

### FE-0.6 契约与测试基线

- 根据 BE-0.5 建立 HTTP/WS 类型、示例 payload 和 mock fixtures；关键 response 不允许使用 `any`
- 引入 Vitest + React Testing Library，先覆盖 API 错误归一化、配置字段映射和基础组件渲染
- 引入 Playwright 配置但本阶段只做应用可打开的冒烟测试，完整流程在后续阶段逐步补齐
- 验收：`npm run build`、`npm run lint`、`npm run test` 全绿；mock payload 与后端 schema 一致

---

## 四、P1：数据链路贯通（2~3 天，最高优先级）

目标：最终 PPT 装的是**这一次真实流程的数据**。对应修复 F1/F2/F3。

### FE-1.1 新建 WizardContext

新建 `src/context/WizardContext.tsx`：

```ts
interface WizardState {
  configStatus: 'checking' | 'ready' | 'missing' | 'degraded';
  topic: string | null;
  dataRef: string | null; // IndexedDB 中原始/清洗数据的引用
  datasetRevision: number | null;
  dataConfirmed: boolean;
  discussionLog: DiscussionEvent[];
  discussionSummary: DiscussionSummary | null;
  discussionSessionId: string | null;
  lastEventSeq: number;
  chartOption: ChartOption | null;
  chartImageRef: string | null; // IndexedDB 中图片的引用
}
```

- Provider 挂载在根组件；`sessionStorage` 只保存步骤、topic、状态标记、session ID、最后 `event_seq` 和 IndexedDB 引用
- 原始数据、清洗数据、较长研讨记录和图表图片写入 IndexedDB，采用节流/显式保存，禁止每次输入都同步序列化大对象
- IndexedDB 写入失败或容量不足时给出明确提示，并允许用户继续当前会话或导出数据
- 提供 `reset()`（开始新课题时清空）
- 提供领域更新方法并执行下游失效：修改 topic 清空数据、研讨、图表、PPT；修改清洗数据清空研讨、图表、PPT；修改研讨清空图表/PPT；修改图表清空已生成 PPT
- 验收：5000 行数据和图表图片可恢复且不触发 sessionStorage 超限；上游修改后不会残留旧成果

### FE-1.2 选题确认修复（修 F2）

- `TopicChat` 的"确认选题"改为弹出 `Modal`：文本域默认填入最后一轮 AI 给出的规范课题名，允许用户编辑
- 确认后 `onTopicSelected(最终文本)` → 写入 context `topic` → 跳转下一步
- 变更已有课题时弹出“将清空后续成果”确认；确认后由 context 统一执行失效规则
- 验收：context 中的 topic 与 Modal 确认文本一致，不再是输入框草稿；旧数据和成果不会混入新课题

### FE-1.3 研讨事件模型与纪要入 context（修 F9）

- 按 BE-0.5 建立 `start/message/finished` 事件处理；保存 `session_id`、单调递增的 `event_seq` 和结构化消息，线上 snake_case 字段不得与内部 camelCase 混用
- 收到 `finished` 时将 `summary` 写入 `discussionSummary`，不再通过“最后一个 writer 字符串”猜测纪要
- P1 仅用 BE-0.5 mock 验证事件入库、`event_seq` 去重和结构化纪要写入；真实 WS resume 归 FE-4.4，与 BE-2.3 联调
- 验收：切换步骤、刷新后本地记录可恢复；mock 补发事件按 `event_seq` 去重；结构化纪要可直接用于 PPT

### FE-1.4 图表截图入 context

- `VisualizationPanel` 持有 `ReactECharts` ref；生成成功后：

```ts
const img = echartsRef.current.getEchartsInstance().getDataURL({ pixelRatio: 2, backgroundColor: '#fff' });
```

- `chartOption` 写入 context，图片写入 IndexedDB 并仅保存 `chartImageRef`
- 图表生成前展示后端采用的转换/聚合口径；用户确认后才进入 PPT
- 验收：图片引用可恢复并可重新生成 dataURL；修改数据后旧图表和图片引用自动失效

### FE-1.5 PPT 真实 payload（修 F1）

`PPTPreview` 的 payload 改从 context 组装：

| 字段 | 来源 |
|---|---|
| `project_name` | 新增输入框，默认取 topic 前 20 字 |
| `topic` | context.topic |
| `data_summary` | 前端生成摘要（行数、列名、数值列 min/max/avg） |
| `discussion_summary` | context 中通过 schema 校验的 `DiscussionSummary` 对象 |
| `chart_images` | 根据 `chartImageRef` 从 IndexedDB 读取，去除 dataURL 前缀后提交纯 base64 |

- 前置校验：缺 topic、已确认数据、结构化纪要或图表时禁用生成按钮并提示缺哪步
- 提交前校验图片类型、数量和解码后大小，避免无效大请求
- 验收：P1 使用契约 mock 验证 payload 来自本次流程真实状态；PPT 文件内容联调作为 BE-4.x + FE-4.6 的共同门禁

### FE-1.6 配置契约对齐（修 F3，与 BE-1.3 联调）

- 表单字段 `max_budget` 改名 `max_budget_usd`
- 回显逻辑改为适配后端真实返回：`has_openai_key` 为 true 时密钥框显示占位 `已配置（不显示）`，留空提交表示不修改
- 保存后重新拉取一次配置刷新回显
- 应用启动时拉取 `configStatus`，状态未确认前保持 `checking`，不提前放行路由
- 验收：预算保存成功；密钥不回显但可更新；刷新页面回显和路由守卫状态正确

### FE-1.7 P1 测试

- 单测：WizardContext 初始化/恢复/容量异常、四级下游失效规则、topic 确认、配置字段映射、PPT payload
- 组件测试：WS finished 写入结构化纪要、`event_seq` 去重、IndexedDB 读取图片失败的提示
- 验收：上述测试全绿，且 mock 数据严格符合 BE-0.5 schema

---

## 五、P2：路由化与状态恢复（1~2 天，修 F4）

### FE-2.1 引入路由

- `npm install react-router`（v7）
- 路由表：

| 路径 | 页面 | 守卫 |
|---|---|---|
| `/config` | ConfigPanel | 无 |
| `/topic` | TopicChat | `configStatus === 'ready'`；degraded 时给出原因与可用能力 |
| `/data` | DataReview | 已有 topic |
| `/discussion` | DiscussionRoom | 已有用户确认的 cleanedData 引用 |
| `/visualization` | VisualizationPanel | 已有用户确认的 cleanedData 引用和 discussionSummary |
| `/ppt` | PPTPreview | 已有 topic、确认数据、discussionSummary、chartOption 和 chartImageRef |
| `*` | 重定向 `/topic` | — |

### FE-2.2 全局 Layout

新建 `src/layouts/WizardLayout.tsx`：

- 顶栏：产品名 + AntD `Steps`（六步，当前步高亮，**已完成步骤可点击回退**）+ 右侧"系统配置"图标入口 + "新课题"按钮（调 `reset()`）
- 内容区 `<Outlet />`
- 守卫组件 `RequireStep`：等待 `configStatus` 和 IndexedDB 恢复完成后再判断；缺失则 `Navigate` 到最早未完成步骤并只提示一次
- 点击已完成步骤回退时允许查看；真正修改上游内容时才触发 FE-1.1 的失效确认

### FE-2.3 App 重构

- `App.tsx` 删除 `currentStep` 状态机，改为 `RouterProvider`/`Routes`
- 各组件回调从"setStep"改为 `useNavigate()` 跳下一步
- 验收：研讨中途刷新进度在；第 5 步可点步骤条回第 2 步改数据再前进；直接访问 `/ppt` 被守卫拦回

### FE-2.4 路由与恢复测试

- 覆盖 checking/ready/missing/degraded 四类配置状态、IndexedDB 尚未恢复、直接访问深层路由、回退查看和确认修改上游内容
- 验收：守卫无闪跳、无重复 message、无无限重定向；刷新后回到最后一个合法步骤

---

## 六、P3：UI 规范化（1~2 天）

### FE-3.1 主题统一

- `App.tsx` 的 `ConfigProvider` 增加 `theme` token（主色/圆角/字号），全项目唯一视觉源头
- 收敛内联色值：`AGENT_CONFIG` 的 hex、头像 `bg-blue-500/bg-green-500`、`PPTPreview` 图标色等改为 token 或语义色

### FE-3.2 统一页面容器

- 新建 `src/components/StepPage.tsx`：标题区 + 内容区 + 底部操作栏（"上一步｜下一步"主按钮位置固定）
- 删除六个组件各自重复的 `min-h-screen flex justify-center items-center bg-gray-50 p-4` 外壳

### FE-3.3 按钮尺寸与图标规范

- 按钮默认按文字内容自适应宽度，禁止仅因布局方便使用大面积固定宽度或 `w-full`；短文字按钮采用 `small`/`middle` 尺寸及紧凑内边距
- "下一步"、"确认生成"等关键主操作保留"图标 + 文字"，避免只靠图标表达复杂业务含义
- 返回、刷新、设置、编辑、删除、关闭、下载等通用轻操作可使用纯图标按钮，统一采用 AntD 图标，并通过 `Tooltip` 提示含义
- 纯图标按钮必须设置 `aria-label`，可点击区域保持一致；同一操作区内按钮高度、圆角、图标尺寸和间距统一
- 同一区域只保留一个主按钮，其余使用 `default`、`text` 或图标按钮，避免多个大按钮并列争抢视觉焦点
- 验收：逐页检查六步页面，无"几个字配一个大空框"的按钮；常用操作紧凑清晰，首次使用者无需猜测图标含义

### FE-3.4 状态三件套 + 错误边界

- 规范：异步加载 `Spin`、无数据 `Empty`、失败 `Result`+重试按钮
- 新建 `ErrorBoundary`（class 组件）包住路由出口，fallback 用 `Result status="500"`

### FE-3.5 组件目录整理

```
src/
├── api/          client.ts
├── components/   StepPage、ErrorBoundary、AgentAvatar 等通用件
├── context/      WizardContext.tsx
├── layouts/      WizardLayout.tsx
├── pages/        六个步骤页（自 components 迁入）
├── types/
└── ...
```

---

## 七、P4：逐步骤体验打磨（2~3 天）

| 页面 | 任务 | 要点 |
|---|---|---|
| 配置页 | FE-4.1 | 连通性检查结果用 `Alert` 展示延迟/错误详情；已配置时步骤条打勾；BE-5.2 就绪后展示 usage、剩余额度和未知费用状态，未就绪时隐藏预算用量区，不伪造 0 消耗 |
| 选题顾问 | FE-4.2 | AI 响应中加打字中状态（Spin 入气泡）；history 按 BE-0.5 已冻结契约传结构化 `[{role, content}]`，不再拼接字符串 |
| 数据清洗 | FE-4.3 | 操作列固定右侧；先展示检测报告和逐列处理策略，用户确认后才应用；支持撤销到原始数据；编辑校验失败红字提示，不再默认自动填补 |
| 研讨室 | FE-4.4 | 与 BE-2.3 联调 **WS 断线重连**（指数退避，最多 5 次）+ `session_id/last_event_seq` 续传 + 按 `event_seq` 去重 + 连接状态 `Tag`；研讨进行中离开需确认；Agent 头像封装 `AgentAvatar` |
| 可视化 | FE-4.5 | "智能推荐图表"按钮（依赖 BE-3.5，未就绪先隐藏）；X/Y 轴相同时拦截；生成前展示数值转换、重复类别聚合规则 |
| PPT | FE-4.6 | 生成前展示内容清单（选题/数据摘要/纪要/图表缩略图）供确认；生成中 `Spin` 全卡片遮罩 |

### FE-4.7 全流程与可用性测试

- Playwright 使用 mock 后端跑通：配置 → 选题 → 上传 → 检测/确认清洗 → 研讨断线恢复 → 图表 → PPT 下载
- 增加失败路径：IndexedDB 容量异常、后端 400/500、WS 重连耗尽、非法图表图片、路由恢复
- 对纯图标按钮检查 `Tooltip`、`aria-label` 和键盘可达性；视觉回归重点检查短文字按钮无大面积留白
- 验收：桌面 1280px 与常用宽屏下全流程无阻塞，错误可恢复，不依赖真实 LLM/API Key

---

## 八、P5（可选，需后端 P6 先行，单独立项）

项目持久化、历史记录列表、多课题并行。前端依赖后端项目 CRUD API，**本计划不含**。

---

## 九、明确不做

- ❌ 迁移 Vue / 换 UI 库 / 引 Redux、Zustand
- ❌ 左侧菜单 Dashboard（无多模块，向导不需要）
- ❌ 自建 design token 体系（用 AntD 6 theme 即可）
- ❌ 移动端适配（桌面工具，保证 1280px+）

---

## 十、工期与里程碑

| 阶段 | 内容 | 工期 | 里程碑 |
|---|---|---|---|
| P0 | FE-0.1~0.6 | 1 天 | 构建干净、契约/测试基线建立、无硬编码地址 |
| P1 | FE-1.1~1.7 | 2~3 天 | 大数据分层恢复、下游失效正确、PPT payload 真实 |
| P2 | FE-2.1~2.4 | 1~2 天 | 配置状态明确、刷新可恢复、步骤可安全回退 |
| P3 | FE-3.1~3.5 | 1~2 天 | 主题/布局/按钮/状态规范统一 |
| P4 | FE-4.1~4.7 | 2~3 天 | 全流程顺滑且通过断线/失败路径测试 |

**合计约 2~3 周。** P0~P2 完成即"可用且可信"，P3~P4 完成"精致、好用、故障可恢复"。

---

## 十一、总体验收清单

- [ ] `npm run build`、`npm run lint`、`npm run test` 全绿，Playwright 核心流程通过
- [ ] HTTP/WS 类型、mock 与后端 BE-0.5 schema 逐字段一致
- [ ] 六步完整走通，PPT 内容 = 真实流程数据
- [ ] 5000 行数据和图表图片不写入 sessionStorage；任意步骤刷新可恢复，容量异常有明确降级提示
- [ ] 已完成步骤可回退查看；修改课题/数据/研讨/图表时按层级清空下游旧成果
- [ ] 配置保存后无需重启后端即生效（依赖 BE-1.x）
- [ ] WS 断线恢复 event 不重复展示，pending command 可继续或明确失败；断网、后端 400/500、重连耗尽均有明确反馈且不白屏
- [ ] 业务源码和生产构建中无 `localhost:8000` 硬编码；开发代理地址仅存在于 `.env.development`，无 JSX 文件残留
- [ ] 全站按钮尺寸随内容合理收敛，无短文字大留白；纯图标按钮均有 `Tooltip` 和 `aria-label`

---

## 十二、风险

1. Tailwind v3→v4 默认值差异导致样式偏移 —— P0 逐页回归兜底
2. AntD 6 较新，`Steps`/`Table` API 与 v5 有差异 —— 以 v6 官方文档为准
3. **浏览器存储容量**：完整数据和图片可能超过 sessionStorage —— 大对象改存 IndexedDB，轻状态只存引用并覆盖容量异常
4. **上游修改导致旧成果污染**：所有写入必须走 WizardContext 领域方法，禁止页面直接修改共享状态绕过失效规则
5. **WS 重连不等于会话恢复**：只有后端支持 session、durable inbox/outbox、event_seq 后才启用 resume；否则明确提示“仅恢复本地记录，需重新开始服务端研讨”
6. **前后端契约窗口期**：FE-1.3/FE-1.5/FE-4.1/FE-4.3/FE-4.4/FE-4.5 依赖 BE-0.5/BE-2.x/BE-3.x/BE-4.x/BE-5.2，必须使用同一套 schema/mock 联调；依赖未就绪时按任务说明隐藏或 mock，不用临时字符串兼容掩盖错误

---

## 十三、直接开发实施规格

本节固定最终文件结构、状态模型、API 调用、页面职责和测试。开发人员按顺序实施即可，不再自行选择另一套状态、存储或路由方案。

### 13.1 目标目录

```text
frontend/src/
├── api/
│   ├── client.ts               axios 实例、AppError 转换
│   ├── config.ts               get/update/check/usage
│   ├── topic.ts                topicChat
│   ├── data.ts                 upload/apply/undo
│   ├── visualization.ts        generate/recommend
│   └── ppt.ts                  generate/getDownloadUrl
├── components/
│   ├── AgentAvatar.tsx
│   ├── ErrorBoundary.tsx
│   ├── IconAction.tsx          Tooltip + aria-label 的纯图标按钮
│   └── StepPage.tsx
├── context/
│   ├── WizardContext.tsx
│   ├── wizardReducer.ts
│   └── wizardTypes.ts
├── hooks/
│   ├── useDiscussionSocket.ts
│   └── useWizardGuard.ts
├── layouts/WizardLayout.tsx
├── pages/
│   ├── ConfigPage.tsx
│   ├── TopicPage.tsx
│   ├── DataPage.tsx
│   ├── DiscussionPage.tsx
│   ├── VisualizationPage.tsx
│   └── PPTPage.tsx
├── routes/router.tsx
├── storage/db.ts               IndexedDB schema 与 CRUD
├── types/api.ts                HTTP wire types（snake_case）
├── types/discussion.ts         WS command/event types（snake_case）
├── test/fixtures/              与后端 schema 一致的 mock
├── App.tsx
├── main.tsx
└── index.css
```

旧 `src/components/*.jsx` 迁移到 pages 后删除，不保留同名双实现。

### 13.2 固定依赖与命令

```powershell
cd frontend
npm ci
npm install react-router idb
npm install -D vitest jsdom fake-indexeddb @testing-library/react @testing-library/jest-dom @testing-library/user-event @playwright/test
npm run build
npm run lint
npm run test
npx playwright test
```

`package.json` 补充：`"test":"vitest run"`、`"test:watch":"vitest"`、`"test:e2e":"playwright test"`。新增依赖后提交 `package-lock.json`，后续安装统一使用 `npm ci`。

Vitest setup 中导入 `fake-indexeddb/auto`，确保 IndexedDB 单测不依赖真实浏览器。

### 13.3 Wire types 与内部状态

HTTP/WS wire type 保持后端 snake_case，不在 API 层做半套字段改名。页面内部需要展示名时通过 selector 转换。

```ts
export interface AppError {
  code: string
  message: string
  details?: Record<string, unknown>
  request_id?: string
}

export interface DataRow {
  row_id: string
  values: Record<string, unknown>
}

export interface ColumnInfo {
  name: string
  inferred_type: 'string' | 'number' | 'percent' | 'date' | 'boolean'
  missing_count: number
  outlier_count: number
  display_format: 'plain' | 'percent' | 'date' | 'datetime'
}

export interface DatasetResponse {
  dataset_id: string
  revision: number
  confirmed_revision: number | null
  filename: string
  columns: ColumnInfo[]
  rows: DataRow[]
  report: CleaningReport
}

export interface DiscussionCommand {
  type: 'start' | 'message' | 'resume' | 'finish'
  session_id: string
  client_message_id: string
  last_event_seq?: number
  topic?: string
  data_summary?: string
  content?: string
}

export interface DiscussionEvent {
  type: 'ack' | 'agent_message' | 'round_done' | 'finished' | 'error'
  session_id: string
  event_seq: number
  timestamp: string
  reply_to_client_message_id?: string
  agent?: AgentRole
  content?: string
  summary?: DiscussionSummary
  round?: number
  recoverable?: boolean
  error?: AppError
}
```

内部状态：

```ts
interface WizardState {
  hydration: 'loading' | 'ready' | 'failed'
  configStatus: 'checking' | 'ready' | 'missing' | 'degraded'
  currentProjectId: string
  topic: string | null
  dataRef: string | null
  datasetRevision: number | null
  dataConfirmed: boolean
  discussionSessionId: string | null
  lastEventSeq: number
  discussionSummary: DiscussionSummary | null
  chartOption: EChartsOption | null
  chartImageRef: string | null
  pptResult: { file_id: string; display_name: string; expires_at: string } | null
}
```

### 13.4 IndexedDB 与 sessionStorage

数据库名 `qcmaker`，版本 1，使用 `idb`：

| store | key | value |
|---|---|---|
| `datasets` | `dataRef` | `{projectId, dataset_id, revision, filename, sourceFile: Blob, columns, rows, report, updatedAt}` |
| `discussion_events` | `[session_id,event_seq]` | 完整 `DiscussionEvent` |
| `chart_images` | `chartImageRef` | `{projectId, blob, mimeType, updatedAt}` |
| `project_state` | `projectId` | `{discussionSummary, chartOption, pptResult, updatedAt}` |

`sessionStorage.qcmaker_wizard` 只保存 `currentProjectId/topic/dataRef/datasetRevision/dataConfirmed/discussionSessionId/lastEventSeq/chartImageRef/currentPath`。Provider 启动顺序：读取轻状态 → 打开 IndexedDB → 读取 project_state 和三个业务 store → 若有 dataset_id 则调用 `GET /api/data/{dataset_id}` 校验 revision/TTL，并以服务端 `confirmed_revision === revision` 重算 dataConfirmed（不信任 sessionStorage 中的旧布尔值）→ 恢复 state → hydration=ready。引用不存在时清除对应步骤及下游状态并提示一次。

首次启动或 `RESET_PROJECT` 使用 `crypto.randomUUID()` 创建 currentProjectId。`SET_DISCUSSION_SUMMARY`、`SET_CHART`、`SET_PPT_RESULT` 成功后立即覆盖写 `project_state`；hydration 从该 store 恢复三项核心结果，不能只依赖内存。写 project_state 失败时不得宣称“已保存”，页面显示可继续使用但刷新会丢失的警告。

所有 IndexedDB 写入经 `storage/db.ts`；组件不得直接调用 `indexedDB`。图片以 Blob 保存，不保存 dataURL；发送 PPT 时临时转 base64。

若 hydration 或后续操作发现后端因 TTL 返回 `SESSION_NOT_FOUND`，DataPage 使用保存的 `sourceFile` 自动重新上传，获得新 `dataset_id/revision` 后更新同一 dataRef，并将 `dataConfirmed=false`、清空研讨/图表/PPT；自动上传失败再要求用户重新选文件。不得拿本地 rows 伪造后端 dataset_id。

### 13.5 Reducer action 与失效规则

固定 action：`HYDRATE_SUCCESS`、`HYDRATE_FAILED`、`SET_CONFIG_STATUS`、`SET_TOPIC`、`SET_DATA_REF`、`CONFIRM_DATA`、`APPEND_DISCUSSION_EVENT`、`SET_DISCUSSION_SUMMARY`、`SET_CHART`、`SET_PPT_RESULT`、`RESET_PROJECT`。

| action | 必须额外清空 |
|---|---|
| `SET_TOPIC` 且值改变 | dataRef、研讨事件/纪要、图表、PPT |
| `SET_DATA_REF`、revision 改变或重新上传 | dataConfirmed=false，并清空研讨事件/纪要、图表、PPT |
| `CONFIRM_DATA` | 仅将 dataConfirmed=true，不改变 revision |
| `SET_DISCUSSION_SUMMARY` 且内容改变 | 图表、PPT |
| `SET_CHART` | PPT |
| `RESET_PROJECT` | 当前 projectId 下四个 IndexedDB store 的数据及全部轻状态 |

失效前若存在下游成果，页面先弹确认框；用户取消则不 dispatch。Reducer 本身仍执行清空，防止调用方漏处理。

### 13.6 API 模块函数

```ts
// config.ts
getConfig(): Promise<ConfigView>
updateConfig(input: ConfigUpdate): Promise<ConfigView>
checkConnectivity(input: ConnectivityRequest): Promise<ConnectivityResult>
getUsage(): Promise<UsageView>

// data.ts
uploadData(file: File): Promise<DatasetResponse>
getDataset(datasetId: string): Promise<DatasetResponse>
previewCleaning(input: CleaningApplyRequest): Promise<CleaningPreviewResponse>
applyCleaning(input: CleaningApplyRequest): Promise<DatasetResponse>
undoCleaning(datasetId: string, baseRevision: number): Promise<DatasetResponse>
confirmData(datasetId: string, revision: number): Promise<DatasetResponse>

// topic.ts / visualization.ts / ppt.ts
topicChat(input: TopicChatRequest): Promise<TopicChatResponse>
generateChart(input: ChartRequest): Promise<ChartResponse>
recommendChart(input: ChartRecommendRequest): Promise<ChartRecommendation>
generatePpt(input: PPTRequest): Promise<PPTResult>
```

Axios interceptor仅处理：超时/网络错误映射、后端错误体解析、保留 `request_id`。页面 catch 后决定如何展示。上传请求不要在 axios 实例全局固定 `Content-Type: application/json`，由浏览器为 FormData 自动生成 boundary。

`ChartRequest` 只提交 `{dataset_id, revision, chart_type, x_axis, y_axis, aggregation?}`，不提交本地 rows；`ChartResponse.processing` 使用后端同名强类型结构，页面生成图表前展示实际 aggregation、转换行和 warnings。

### 13.7 路由与守卫算法

```text
/config         无前置条件
/topic          configStatus=ready
/data           topic 非空
/discussion     dataRef、datasetRevision 存在且 dataConfirmed=true
/visualization  discussionSummary 非空
/ppt            chartOption、chartImageRef、discussionSummary 均存在
```

守卫等待 hydration 与 config checking 结束后才重定向。若条件不满足，计算“最早缺失步骤”并 `replace` 跳转；同一次导航只提示一次。degraded 状态允许进入 config 查看原因，不允许进入依赖 LLM 的 topic。

### 13.8 WebSocket hook

`useDiscussionSocket` 对外只返回 `{status, events, sendMessage, finish, retry}`。组件不直接持有 WebSocket。

- `status`：`idle | connecting | connected | reconnecting | finished | failed`
- start：生成 UUID session/client message，发送 topic 和数据摘要
- onmessage：先校验 JSON 与 event type；`event_seq <= lastEventSeq` 丢弃，否则按序写 IndexedDB 后更新 context
- 发现序号跳跃时立即关闭连接并走 resume，禁止直接展示不连续事件
- reconnect：1s、2s、4s、8s、16s，最多 5 次；resume 携带最后已持久化的 `last_event_seq`
- 组件卸载只关闭 socket，不删除 session；finished 后停止重连
- `retry` 只处理网络断开或 `recoverable=true` 的 error：先 resume，再由用户确认是否重发原命令并生成新的 client_message_id；`recoverable=false` 时禁用输入，只允许新建 session 或回到数据页
- `finish` 仅在 connected 且会话未 finished/error 时可用；发送后禁用输入，收到 ack 后显示“正在收尾”，收到 finished 后写入纪要并停止重连

### 13.9 六个页面的直接实现清单

| 页面 | 必须实现 | 主操作 |
|---|---|---|
| ConfigPage | 加载/保存配置、密钥占位、连通性、可选 usage | “保存并继续” |
| TopicPage | 结构化 history、loading 气泡、课题确认 Modal | “确认课题” |
| DataPage | 上传后仅检测；选择逐列/逐行规则 → 调 preview 对比影响 → 用户确认后调 apply → 保存新 revision；undo 也生成新 revision；点击主操作时先调 confirm 成功，再 dispatch `CONFIRM_DATA` | “确认数据” |
| DiscussionPage | 连接状态、事件列表、断线恢复、finished 纪要预览 | “结束研讨” |
| VisualizationPage | 字段选择、推荐、处理口径确认、ECharts、截图 Blob | “确认图表” |
| PPTPage | 项目名、四类内容清单、缩略图、生成、下载与过期时间 | “生成 PPT” |

每页统一使用 `StepPage`，异步区必须覆盖 loading/empty/error/retry；底部操作栏固定但按钮只按内容宽度，不使用 `w-full`。

### 13.10 UI 精确规格

- 内容最大宽度：普通页面 `960px`，数据/图表页 `1200px`；页面水平内边距 `24px`
- 默认按钮高 `32px`，主流程按钮高 `36px`；短文字按钮水平内边距 `12px`，禁止设置无业务意义的固定大宽度
- 纯图标按钮统一 `32×32px`，仅用于返回、刷新、设置、编辑、删除、关闭、下载；必须使用 `IconAction`，自动提供 Tooltip 和 `aria-label`
- 同一操作区只允许一个 `type="primary"`；危险操作使用 `danger` 并二次确认
- 按钮间距 `8px`，卡片间距 `16px`，页面区块间距 `24px`；不使用多个超大 Card 嵌套
- 关键动作使用“图标+文字”，不把“确认课题、确认数据、生成 PPT”等业务动作改成纯图标

### 13.11 文件改动矩阵

| 任务 | 必改文件 | 同步测试 |
|---|---|---|
| FE-0.x | main/App、api client、types、Vite/Tailwind/TS 配置 | API 错误与 smoke 测试 |
| FE-1.x | context/reducer、storage、Topic/Data/Discussion/Visualization/PPT pages | reducer、存储、payload、事件测试 |
| FE-2.x | router、guard hook、WizardLayout | 路由矩阵测试 |
| FE-3.x | StepPage、IconAction、ErrorBoundary、theme | a11y 与按钮规格测试 |
| FE-4.x | 六页面体验、socket hook | 组件测试 + Playwright 全流程 |

### 13.12 测试用例与完成定义

必须覆盖：配置密钥不回显；上传 10MB/格式错误；检测不改原值；preview 不落库；apply/undo revision 单调递增；confirm 前守卫拦截；dataset TTL 后用 sourceFile 重传；修改 topic/data 清空下游；project_state 刷新恢复；IndexedDB 引用丢失；WS ack/round/finished、重复/乱序/断线/可恢复与不可恢复 error；图表按 dataset revision 请求及 processing 展示；图表图片 Blob 恢复；PPT payload 真实；file_id 下载；400/409/422/500/网络错误；按钮 Tooltip/aria-label。

任务完成条件：实现文件与删除清单均处理；类型无 `any` 逃逸；mock 与后端 schema 一致；build/lint/unit/e2e 对应门禁通过；1280px 下无布局溢出；页面不存在短文字大按钮；刷新和失败路径可恢复。只完成视觉稿或只跑通正常路径均不算完成。

### 13.13 建议提交顺序

1. `FE-0-foundation`：安装依赖、删除模板、TS/API types、Vite/Tailwind、测试基线
2. `FE-1-state-storage`：IndexedDB、reducer、Provider、失效规则
3. `FE-1-data-flow`：Config/Topic/Data 页面及后端 upload/apply/undo 联调
4. `FE-2-routing`：Router、Layout、守卫、刷新恢复
5. `FE-1-discussion-chart-ppt`：WS 事件入库、图表 Blob、PPT payload（先用契约 mock）
6. `FE-3-ui-system`：StepPage、IconAction、主题、紧凑按钮和错误状态
7. `FE-4-integration`：与 BE-2/3/4/5 联调，完成 WS resume、usage、PPT 下载和 Playwright

每个提交合并前运行该阶段对应的 build/lint/test；涉及 wire type 的提交必须与后端 schema 或 mock fixture 同步，禁止先用 `any` 临时打通后再补类型。
