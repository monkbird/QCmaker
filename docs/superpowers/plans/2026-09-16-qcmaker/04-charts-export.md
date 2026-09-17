# QC图表与章节成果导出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 图表和成果使用同一版章节数据，支持QC论证并保持来源、数值与时间口径一致。
**Architecture:** 消费03不可变ChapterSnapshot及02证据引用；图表生成确定性数据规格，PPT按章节快照组装；保留既有下载认证与资源清理机制。
**Tech Stack:** 现有 Python图表/PowerPoint生成栈、ECharts、React、pytest、Vitest。
**Spec:** [需求总纲](../../../QCmaker修改需求汇总与规划.md) 第7章、9章、10章及11.2、11.5、11.7。

## Global Constraints

- 仅文档规划，以下文件、接口和测试设计均尚未实施。
- 不把所有QC工具做成强制图表；不得以美化改变数值、对照关系或证据性质。
- 图表、正文及导出保留待核实、模拟标识；作者审核不等于事实核实。
- C0通过后可对契约样例开发；真实章节联调须等03交付。

## 1. 文件与依赖

本包独占现有文件：`backend/app/services/chart.py`、`backend/app/services/ppt.py`、`backend/app/api/endpoints/visualization.py`、`backend/app/api/endpoints/ppt.py`、`frontend/src/pages/VisualizationPage.tsx`、`frontend/src/pages/PPTPage.tsx`、`frontend/src/api/visualization.ts`、`frontend/src/api/ppt.ts`。

拟新增：`backend/app/models/reporting.py`、`backend/app/services/report_validation.py`、`backend/app/repositories/artifact_repository.py`、`frontend/src/types/reporting.ts`、`frontend/src/components/reporting/`；专属测试为`backend/tests/test_qc_charts.py`、`test_chapter_export.py`、`test_report_consistency.py`、`frontend/src/test/chapterExport.test.tsx`。旧PPT、图表生命周期及跨流程测试由05统一适配。

本包不修改公共contracts、WizardContext、路由或数据库初始化；提交领域迁移需求及事件消费说明给协调者。`api/insight.ts`由05接入，必要的新调用先放本包专属API文件。

## 2. R1：阶段图表与计算

- [ ] 建立ChartSpec：项目、章节及revision、metric_id、图表类型、数据来源版本、分组、单位、时间范围、比较方式、计算方法、性质标识。新规格与旧bar/line/pie请求通过显式适配兼容。
- [ ] 优先保留并增强柱形、折线、饼图；新增排列图支持频数排序、累计占比与总量核对；原因分析支持结构化原因树，必须显示假设/已确认区别。后续工具按实际需要追加，不承诺附录所有工具本轮实现。
- [ ] 对单位、分母、分组和采样条件做确定性检查；均值、增幅、占比、累积百分比由代码计算，模型只推荐表达方式。
- [ ] 百分比指标不默认对不同分母简单平均；若缺分母或加权条件，提示选择口径，不能默默套mean。无基线、零基线、缺测不强造增幅。
- [ ] 显示数据版本及性质；估测/实测、对照/前后与模拟不得混写；坐标截断等影响理解的选择明确显示。

验收：总数为150、频数108时占比为72%，但该算术成立不能证明记录真实；337.04至374.29增幅约11.05%，不同来源写11.30%须提示冲突。以上只用作逻辑样例，不新认定任何项目事实。

## 3. R2：全文章节与导出

- [ ] 改为选择课题路径和章节快照组装PPT，不从一份DiscussionSummary直接推导全部阶段。保留现有模板、分页、文件原子写入及下载认证。
- [ ] 每章至少消费标题、正文块、指标表、图表引用及证据状态；小组概况和阶段内容按照03路径排序，缺证据允许导出草稿。
- [ ] 导出预检展示缺章、未审核、引用失效、数值冲突、模拟和待核实内容；错误分级：损坏/跨项目/无法读取版本阻止生成，缺证据允许明确标识的草稿输出。
- [ ] 草稿与确认稿模式不改变底层来源性质；确认稿仍不得自动擦除模拟标识。标题、表格、脚注和附录中的状态一致。
- [ ] 同一次导出固定全部输入revision，生成中上游变化不混入；保留输入快照和旧产物，新版另生成。

拟议新增请求：`POST /api/ppt/generate-from-chapters`，输入project_id、chapter_revisions、chart_revisions、template_id、mode、operation_id；返回artifact_id、输入版本、预检摘要和既有受保护下载引用。确切字段在C0冻结；旧`PPTRequest`暂留兼容适配，不能让旧接口生成内容冒充新路径完整成果。

## 4. R3：失效、恢复与交接

- [ ] 消费02 MaterialChangedEvent及03章节版本事件，按依赖标记关联图表和报告stale；不删除全部项目成果。
- [ ] 生成失败保留已有可用产物，状态说明失败原因；取消/重复操作不重复写文件或计费。快照已失效的导出入口提示更新，旧版仍可查。
- [ ] 为05提供ArtifactSnapshot、所需数据库元数据字段、项目恢复样例及过期资源保护规则。被章节引用的资料不能被原TTL策略直接清除。
- [ ] 验证长标题、多页表格、空章、中文和图表密集页；查看实际导出的PPT及必要渲染结果，不能只凭生成文件存在声称排版通过。

测试目标：

```text
python -m pytest backend/tests/test_qc_charts.py backend/tests/test_chapter_export.py backend/tests/test_report_consistency.py -q
cd frontend
npm run test -- src/test/chapterExport.test.tsx
```

测试断言应覆盖输入快照一致、跨项目拒绝、标识保留、分母缺失处理、旧版产物留存和失败不覆盖；图片快照只用于稳定布局，不用整页截图替代数值校验。实际PPT视觉检查由05汇总证据。

## 5. 包级完成条件

- [ ] 三类以上章节样例（有真实引用、证据缺失、模拟）均能形成对应预检与输出。
- [ ] 正文、表格和图表共用计算结果；版本变化可定位受影响产物。
- [ ] 新旧接口及下载保护回归已向05说明；无未登记的共享文件修改。
- [ ] 记录测试及视觉检查范围，未实际检查的模板或平台明确列为未验证。
