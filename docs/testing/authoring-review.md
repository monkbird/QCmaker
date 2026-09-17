# Authoring 前后端独立审查（2026-09-16）

## 集成复核状态

以下为修复前审查。集成阶段已落实：事实核实先解析真实来源，再要求依据已登记在本章，否则返回 `EVIDENCE_NOT_LINKED`；手动保存使用输入摘要和操作号持久化，重放返回同一版本，变更输入返回冲突；场景 body 与路径项目不一致返回 `PROJECT_CONFLICT`。历史接口返回快照，影响预览中的章节对象由前端映射为 ID。回归包括 authoring integration、完整浏览器无 Excel 流程及历史恢复。

审查范围：`backend/app/services/authoring.py`、`backend/app/api/endpoints/authoring.py`、`frontend/src/pages/AuthoringPage.tsx`、`frontend/src/components/authoring/ChapterReview.tsx`、`frontend/src/api/authoring.ts`。本次只读审查，未修改实现。

## P1：事实核实可引用未归属本章的证据

位置：`backend/app/services/authoring.py:127-136`。

重现条件：

1. 在项目 `p` 注册一个来源 `source-a v1`，来源性质为 `user_reported` 或 `documented`。
2. 创建/保存章节 `ch1 v1`，其 `evidence_refs=[]`。
3. 调用 `POST /api/projects/p/chapters/ch1/evidence-verification`，提交 `evidence_state=verified`、`basis=[source-a v1 的合法 EvidenceRef]`、`gaps=[]`。

实际路径只执行 `resolve_sources(project_id, req.basis)`，没有要求 basis 引用已登记在当前章节，也没有把 basis 写入 `snapshot.evidence_refs`。因此接口会返回新的章节快照并标记 `evidence_state=verified`，但快照本身没有任何 `evidence_refs`，后续报告/图表无法从章节快照追溯这次核实依据。这是可复现的伪证据状态，应拒绝未归属章节的 basis，或在同一事务中明确追加并记录其版本。

前端放大了该问题：`AuthoringPage.tsx:213` 的“本章依据”只更新内存 `chosen`，点击 `ChapterReview.tsx:14` 的“以所选依据核实事实”时直接把 `chosen` 作为 basis 发送；若用户从列表选择依据后不先保存章节，仍可进入上述路径。

## P1：章节保存声明了 operation_id，但后端丢弃幂等语义

位置：`backend/app/models/authoring.py` 的 `ChapterUpdate.operation_id` 与 `backend/app/services/authoring.py:110-122`。

重现条件：对同一项目、章节、`expected_revision` 和同一个 `operation_id` 连续发送两次相同 `PUT /api/projects/p/chapters/ch1`。服务层最终调用 `repository.save_snapshot(snapshot, request.expected_revision)`，没有传入 `request.operation_id`，所以两次请求不会复用第一次结果；第一次成功后第二次通常返回 `REVISION_CONFLICT`，在客户端超时重试时无法得到同一结果，只能重新构造请求。该接口模型既然暴露 operation_id，当前实现会造成“请求已成功但客户端未收到响应”时无法安全重放，并可能留下调用方无法对应的版本记录。

## P2：场景接口静默改写跨项目 body

位置：`backend/app/api/endpoints/authoring.py:21-24`。

当路径为 `/projects/p/...` 而 JSON body 的 `project_id` 为 `q` 时，接口静默执行 `model_copy(update={'project_id': project_id})` 后写入 `p`。这不会把资料写入错误项目，但会掩盖前端/调用方的项目串线并返回看似成功的 `p` 对象。与章节、资料接口对项目范围不一致，建议至少返回明确的项目范围冲突，避免调用方误以为 `q` 已保存。

## sessionStorage 草稿检查

`ChapterReview.tsx:7-9` 使用 `qc-chapter-draft:{project_id}:{chapter_id}:{revision}` 分区，项目和章节不会互相覆盖；内容、结构化块和指标编辑均会即时写入，解析失败和存储失败有可见错误提示。当前未发现跨项目覆盖。

但保存成功后没有清理旧 key。由于 revision 纳入 key，下一版不会读取旧版本草稿，主要影响是长期积累无界 sessionStorage 项；这不是当前 P1 数据损失问题。刷新恢复依赖服务返回同一 revision，保存产生新 revision 后会自然切换到新 key。

## 未发现的范围项

历史接口按 `project_id` 和 `chapter_id` 查询，快照列表没有跨项目 SQL 泄漏；前端章节切换使用 `key={state.currentProjectId}`，项目切换时会重新挂载编辑器。以上结论为静态审查结论，主代理正在执行端到端验证。
