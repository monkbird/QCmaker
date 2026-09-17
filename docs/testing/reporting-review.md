# Reporting 模块审查记录（2026-09-16）

## 审查范围

依据 `docs/superpowers/plans/2026-09-16-qcmaker/03-authoring-review.md` 与 `04-charts-export.md`，审查章节图表、章节导出、成果仓库、预检及 reporting/PPT 端点涉及的实现。未修改 materials、config、frontend、root authoring 文件。

## 发现与处理

1. 指标 `metric.refs` 和原因树节点引用此前可仅凭快照中的 JSON 使用，未验证是否登记在本章、是否属于当前项目、来源版本和定位是否仍存在。已在 `report_validation.py` 增加来源解析校验：资料引用必须存在于当前项目的资料版本；网页、用户、派生引用必须匹配当前项目的 `source_version` 活动记录；模拟来源保留为明确的模拟性质。缺失来源会阻止图表和章节导出预检。
2. 原因树节点此前以 `confirmed=true` 且存在任意 `evidence_refs` 即显示“已确认”。现改为同时要求引用属于章节来源，并存在结构化确认记录（method、object、time、criterion、result）；只有 ref 的节点显示“假设/待确认”。
3. 成果仓库陈旧传播此前依赖数据库返回顺序。导出可能先于其图表被处理，导致一次重启恢复漏标。已改为按依赖传播至稳定点，保留旧产物并累积待复核原因。

## 验证证据

执行：

```text
python -m pytest backend/tests/test_qc_charts.py backend/tests/test_chapter_export.py backend/tests/test_report_consistency.py -q
10 passed in 0.82s
```

新增回归断言验证：原因树只有 ref 不会被标为已确认。既有测试继续验证排列图累计占比、零基线拒绝、跨项目章节拒绝、导出幂等、模拟/待核实标识、跨项目导出拒绝及章节变化后的成果陈旧标记。

已使用项目 `.venv/Scripts/python.exe` 执行同一测试命令。另在隔离 SQLite 中真实调用 `chapter_reporting.generate_chart`（Pareto）和 `chapter_reporting.export_chapters`，输入长中文正文、表格、模拟值和待核实块，生成 `.venv/acceptance/reporting/generated/69950778-2fec-4bc4-b2c2-78535ce35715.pptx`。该实际导出共 9 页；通过本机 PowerPoint COM 导出 `reporting-chapter-export.pdf`，再用 Poppler 渲染全部 9 页 PNG，逐页检查标题、中文正文、表格/图表、分页和底部状态标识，未见文字超出页面。该样例不替代真实用户材料和正式模板的完整视觉验收。

## 交接说明

改动文件：

- `backend/app/services/report_validation.py`
- `backend/app/repositories/artifact_repository.py`
- `backend/tests/test_qc_charts.py`
- `docs/testing/reporting-review.md`
- `.venv/acceptance/reporting/generated/69950778-2fec-4bc4-b2c2-78535ce35715.pptx`
- `.venv/acceptance/reporting/reporting-chapter-export.pdf`
- `.venv/acceptance/reporting/page-1.png` 至 `page-9.png`

契约字段未修改，数据库迁移未修改。确认稿仍会保留模拟、假设、待核实和陈旧标识。
