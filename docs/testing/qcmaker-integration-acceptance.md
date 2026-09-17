# QCmaker 本轮实施与集成验收

日期：2026-09-16。起点：`a251ae3`。实施分支：`codex/qcmaker-plan-implementation`。

用户本轮请求为按计划修改项目；计划中“仅修改文档”的语句属于此前阶段。本轮保留用户原有总纲和计划文件，不提交 Git、不合并、不部署，不在用户正式数据库上执行迁移。

## 已接入的使用流程

| 领域 | 当前实现 |
|---|---|
| 配置 | 命名方案、另存/切换、可选默认模型、角色服务绑定、服务级模型目录刷新、统一草稿探测、独立搜索验证、凭据引用及部署锁 |
| 资料 | 流式原件存储、版本隔离、页/幻灯片/工作表解析、中文本地 OCR、定位及覆盖明细、清洗预览/确认/幂等重放/撤销、跨项目引用拒绝 |
| 章节 | 问题解决型自定目标/指令性目标各11部分、场景卡、手写或模型生成、未保存正文会话恢复、内容形成/作者审核/事实核实分离、章节历史和恢复、范围变更预览 |
| 来源与活动 | 资料/网页/人工/模拟来源登记与版本引用；活动日期、负责人、对象、措施机制、观察记录；时间顺序及指标口径检查 |
| 图表与成果 | 固定章节版本的柱形/折线/饼图/排列图/原因树、确定性计算、导出前预检、草稿/作者确认稿、PPT分页及性质标识、历史下载、上游变化提示 |
| 集成 | 无Excel可进入章节工作台、项目历史恢复、多数据集切换、IndexedDB v1→v2、SQLite追加迁移、旧讨论及成果入口保留 |

## 可复核的测试结果

使用项目独立 Python 3.13 虚拟环境，解决本机全局 Python 的 NumPy/Pandas 二进制不兼容，不修改全局环境。

| 检查 | 结果 | 本地日志 |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest backend/tests -q --disable-warnings` | 210 passed，2 warnings | `.venv/backend-delivery.txt` |
| `npx vitest run --maxWorkers=2` | 20 files，58 passed | `.venv/frontend-final-verified.txt` |
| `npm run lint` | 通过，无错误 | `.venv/lint-business-final.txt` |
| `npm run build` | 通过；图表依赖有大包体提示 | `.venv/build-business-final.txt` |
| Playwright，新旧流程合跑 | 6 passed | `.venv/e2e-verified.txt` |
| 报告提示改用中文章节名称后相关回归 | 通过 | `.venv/report-final-verified.txt` |
| 真实调用与探测统一网关后的配置/角色/安全/搜索回归 | 40 passed，2 warnings | `.venv/gateway-delivery.txt` |
| `git diff --check` | 通过 | 无差异格式错误 |

Playwright 覆盖：无Excel手写章节→作者审核→刷新恢复→预检→生成并下载PPT；真实API资料上传→清洗→撤销；浏览器清洗逐项确认；配置页面；桌面/窄屏控件；旧数据清洗→讨论恢复→图表→鉴权下载→断网恢复→标题修改。新流程通过 `backend/tests/run_local_acceptance.py` 使用隔离 SQLite 与文件目录，旧流程的模型响应及网络传输使用替身。执行结束后重新生成常规生产构建，不保留 E2E 测试令牌构建作为发布件。

## 真实文件与视觉验收

- 中文合成 PNG 和扫描 PDF 使用真实 RapidOCR + PyMuPDF，断言正确中文输出；测试位于 `backend/tests/materials/test_real_ocr.py`。缺少 Windows 中文字体的平台会明确跳过该本机验收项。
- 指定标准原件只读复制到 `.venv/acceptance/standard/`；原件 12,905,586 bytes，SHA-256 `f7531a68498941ee609a4a00c2ad326a767906843bef88fd3696247cb173ed75`。真实上传及解析得到20个页记录，18页取得内容，PDF第2、8页未识别到文字，保留失败定位和 `needs_review`。总纲将这两页记为空白页；程序未据此自动认定全件核验完成。原文未外发、不进入 Git。
- 通过实际 `chapter_reporting.generate_chart` 和 `export_chapters` 生成9页中文长正文、结构化表格、模拟标识与排列图样例，PowerPoint COM 导出PDF，Poppler渲染9页。产物位于 `.venv/acceptance/reporting/`，已检查分页及中文可读性；正文表格当前以分页文字行呈现，排列图附累计比例说明页。
- 浏览器截图和实际下载成果位于 `.venv/acceptance/authoring.png`、`export.png`、`browser-report.pptx`。

## 边界及尚未证明的事项

- 没有使用用户真实模型/搜索凭据进行付费服务验收；角色路由、预算及失败恢复的离线测试通过，不等于任何外部套餐均可用。Anthropic 原生接口等未支持能力明确返回不可用。
- 当前路径明确使用用户提供的2020参考版本。未完成2024逐条差异及申报方规则核验；创新型路径不自动生成。
- OCR覆盖记录不等于版面、公式、流程图或事实已正确理解。扫描图表、脚注、复杂表格仍需要对照原文；两份业务研究材料和真实QC成果尚未完成专属语义验收。
- 资料建议按章节用途对完整解析内容进行关键词定位，给出采用理由及支持边界；作者仍可手动排除或改归属。指标、表格和原因树修改会展示前后对照，再保存为待审核版本。关键词定位不等于智能因果判断；上游资料更新按关联章节/成果保守提示复核，不自动替换结论。
- 未进行生产迁移或发布。升级及回退操作边界见 `qcmaker-migration-recovery.md`。

本记录区分已实现、已测试和外部条件未验证的部分；不将整份计划的全部复选框自动标记为完成。
