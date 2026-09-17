# 场景检索、逐章编写与审核 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 少资料或无资料也能进入QC编写，按章节形成草稿、审核并检查活动时间及效果论证。
**Architecture:** 新增独立章节工作台及版本仓库，复用现有模型和研讨能力；材料由02管理，报告由04消费章节快照。
**Tech Stack:** FastAPI、Pydantic、SQLite、React、Ant Design、pytest、Vitest。
**Spec:** [需求总纲](../../../QCmaker修改需求汇总与规划.md) 第5—7章、第10章、11.3—11.7。

## Global Constraints

- 本轮只写规划；所有新增文件、接口、模型、测试均为未来设计，00冻结后才能实施。
- 不要求先上传Excel，不把现场活动实时完成作为写作前置条件；报告中的活动日期、实施过程和因果关系仍需核对。
- 模拟和假设用于可审核草稿，资料记载、作者确认表达与事实核实分别保留；不依据获奖目标篡改来源性质。
- 自定目标与指令性目标按适用版本分支；创新型本轮仅保留类型边界，未经确认不自动扩大实现范围。

## 1. 排他文件归属与输入输出

本包可修改：`backend/app/services/search.py`、`backend/app/api/endpoints/search.py`、`backend/app/api/endpoints/topic.py`、`frontend/src/pages/TopicPage.tsx`、`frontend/src/api/topic.ts`。为防止大范围重写，原研讨事件/恢复逻辑优先只读复用；需要修改`discussion_session.py`、讨论端点、`DiscussionPage.tsx`、`useDiscussionSocket.ts`或`types/discussion.ts`时，由协调者先登记归本包，其他包不得同时修改。

本包拟新增：

- 后端`models/authoring.py`、`services/authoring.py`、`services/qc_paths.py`、`services/timeline_checks.py`、`repositories/authoring_repository.py`、`api/endpoints/authoring.py`。
- 前端`types/authoring.ts`、`api/authoring.ts`、`api/search.ts`、`pages/AuthoringPage.tsx`、`components/authoring/`。
- 后端测试`test_authoring_paths.py`、`test_authoring_review.py`、`test_authoring_versions.py`、`test_authoring_timeline.py`、`test_search_status.py`；前端`src/test/authoringReview.test.tsx`。

共享类型、数据库迁移执行、全局状态、向导守卫和路由由00/05负责；不直接修改。02的MaterialWorkspace嵌入TopicPage时由本包删除旧上传区及10MB校验。01保持ConfigPage所有权，本包只提供搜索能力与测试接口。

输入：00证据契约、01角色路由、02资料及解析覆盖状态。输出：项目场景、候选课题、章节内容与三类状态、不可变ChapterSnapshot及依赖失效清单。

## 2. 任务A1：场景与联网研究

- [ ] 建立场景卡：地区/地点、工程或作业对象、环境与季节、人员能力和数量范围、机械及工法、活动时间、现有问题、预期改善指标、已有资料、受限条件。每项保留用户指定/资料提取/网络参考/假设来源；未知项允许空缺。
- [ ] 允许“直接给定课题”和“提供场景后推荐多个课题”；课题候选说明适用性、所需关键资料、可量化指标及需核实的假设，由作者选择或继续讨论。
- [ ] 少资料、无资料均支持检索；按场景生成地区、对象、时期、工艺、环境、人员约束检索维度，可由作者调整。检索来源保留标题、URL、发布/访问日期及适用条件；外地、不同年度和不同工况显式提示差异。
- [ ] 将搜索服务的空列表改为结构化状态：not_configured、failed、empty、success；保留旧消费者适配。无网络结果时仍可编辑草稿，但不能显示“已联网核实”。
- [ ] 提供搜索实际验证给01。参数使用当前草稿配置的服务地址/凭据引用及固定小查询；结果含状态、耗时、错误摘要和可访问来源，不返回密钥；参数在C0与01统一。
- [ ] topic普通聊天显式传`role="topic"`；按project_id保存和恢复讨论。资料中的指令只作为材料内容，不覆盖用户请求或系统规则。

验收：同一场景无附件也可形成候选；仅有研究总结不要求补Excel；搜索失败和成功但无结果分开；模型响应不能凭未检索的链接声称有依据。

## 3. 任务A2：路径与逐章草稿

- [ ] 以标准版本、课题类型、目标来源生成稳定chapter_id及顺序；小组概况与标准活动步骤分开。自定目标十个步骤加概况形成十一部分；指令性目标按总纲第10章路径映射，不强塞两条分支的全部步骤。
- [ ] 本轮先实现总纲已明确的问题解决型路径；标准版本未核定时显示所用参考版本及待核定状态，不自动把2020内容标成2024条文。
- [ ] 每章定义“任务目的、已有证据、需要形成的结论、可用分析方式、缺项和下章输入”。原因分析、要因确认、制定对策、对策实施、效果检查必须独立建模。
- [ ] 逐章生成正文、表格候选、假设及待补项；模拟值保留来源性质、合理范围依据和生成假设，不生成假冒真实第三方报告或检测编号。
- [ ] 资料推荐按章说明为什么相关、可支持什么、不能支持什么。作者可接受、排除或改归属；同一来源可多章复用，引用指向版本。
- [ ] 根据全文覆盖摘要及可定位EvidenceBlock分批读取；相关检索只用于定位，不能用三段片段冒充全文审阅。模型实际未覆盖部分在阅读状态中说明。

拟议API：`GET/PUT /api/projects/{project_id}/context`；`GET /chapters`；`POST /chapters/{chapter_id}/generate`；`PUT /chapters/{chapter_id}`；`GET /chapters/{chapter_id}/snapshot?revision=N`。生成输入包括expected_revision、operation_id和选定来源版本。写入冲突遵守00约定。

验收：只有问题和措施也能生成带缺项的后续草稿；不能把原因字符串直接登记为已确认要因；确认结果应表达确认方法、对象、时间、判据、结果、影响程度与证据。

## 4. 任务A3：审核与状态

- [ ] 按00三类状态实现审核记录，记录人、日期、适用revision、意见和依据；支持接受、退回、保留待核实项继续。
- [ ] 简单文字支持批量确认；指标基线、目标、要因、措施、效果和数据性质变更展示逐项对照，不能隐含在一键“全文通过”中。
- [ ] 草稿内容完成不要求事实已齐；作者同意表达不改变证据状态。拟议`POST /chapters/{chapter_id}/review`与`POST /chapters/{chapter_id}/evidence-verification`分开，后者必须提交依据及缺项处理。
- [ ] 展示章节概览和下一项建议，支持回到上章及跨章补资料；保存失败不显示成功，刷新恢复同一项目和审核版本。

验收例：要因章内容完整，作者接受，但缺现场确认记录，应为`complete/approved/partial`，允许进入对策草稿。后续上传真实确认资料须重新核对，不能自动变成verified。

## 5. 任务A4：时间、指标与贡献判断

- [ ] 分开存储活动发生时间、材料记录时间、上传时间、编写时间；日期未知保留空缺或待补，不用上传日期倒填活动日期。
- [ ] 实施记录关联措施、对象、负责人、开始/结束、过程指标、观察期、证据或假设。缺少资料可形成拟议情景，状态保持假设或模拟。
- [ ] 确定性校验单位、分母、样本对象、估测/实测、对照/前后、先后顺序及计算；地域季节、生物生长或工法观察期依场景资料提出待复核意见，不凭通用常识写死阈值。
- [ ] 每项措施关联预期作用机制、观察结果和支持程度；共同实施时不擅自分配贡献率。未达标保留原结果和后续改进轮次。
- [ ] 对样例337.04与374.29按原比较对象计算约11.05%，不能自动认定活动前后实测；样例有机质冲突只提示，不猜值替换。

## 6. 任务A5：变更影响与交接

- [ ] 名称润色仅更新展示；对象、指标、范围、课题类型等变更先列受影响章及成果，由作者选择局部重审或新方案，保留历史。
- [ ] 建立来源版本→指标/结论→章节→图表/报告依赖；资料清洗变化、新版采用、目标变化只标记受影响对象。旧版可查，不覆盖全章。
- [ ] 将拟议影响分析API `POST /api/projects/{project_id}/changes/preview`及应用API `POST /changes/apply`、图表失效事件样例交给05接入全局状态。
- [ ] 提供04消费的章节快照样例：完整、有缺项、模拟、失效四类；显式区分正文块、指标表、引用和审核状态。

测试目标：

```text
python -m pytest backend/tests/test_authoring_paths.py backend/tests/test_authoring_review.py backend/tests/test_authoring_versions.py backend/tests/test_authoring_timeline.py backend/tests/test_search_status.py -q
cd frontend
npm run test -- src/test/authoringReview.test.tsx
```

关键断言：模拟数据即使审核通过仍保留simulation；重复operation_id不重复生成；上游变化只使关联章节过期；无资料不被旧数据守卫退回；其他项目不可读快照。网络和模型使用确定性替身验证逻辑，真实服务另由05按实际配置验证并分别记录。

完成交接必须含：改动文件、契约版本、快照样例、测试结果、未完成项；不得仅以“页面能打开”声明任务完成。
