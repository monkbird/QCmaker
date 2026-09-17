# Package 03 authoring acceptance

> 集成更新：路由、资料区和章节工作台均已接入；章节生成现调用 writer 模型并在失败时保留旧版本，不再使用固定占位内容冒充生成成功。本文下方的“限制与交接”是最初交接记录，以 `qcmaker-integration-acceptance.md` 的最终状态为准。

契约版本：QC C0 v2；标准路径默认引用 `T/CAQ 10201-2020`，适用版本仍由作者核定。

已交付：

- `ScenarioCard` 保留场景字段及字段来源性质；`TopicCandidate`、章节审核与事实核实请求模型独立建模。
- `qc_paths.chapter_path()` 为问题解决型自定目标生成稳定章节 ID；指令性目标移除不适用的目标章节。
- `AuthoringRepository` 严格按 `project_id` 查询冻结 chapters/project_contexts 表，快照按 revision 追加保存，生成 operation_id 幂等。
- `AuthoringService` 明确生成章节草稿，模拟/待补内容保持 `draft`、`missing` 和缺项原因；作者审核与证据核实分开。
- 搜索服务返回 `not_configured`、`failed`、`empty`、`success`，来源带 URL、标题、访问时间及适用条件。
- 时间检查不会用上传时间填充活动时间；前端提供场景卡、章节列表、明确生成、审核和保留待核实项继续操作。

验证证据：`python -m pytest backend/tests/test_authoring_paths.py backend/tests/test_authoring_review.py backend/tests/test_authoring_versions.py backend/tests/test_authoring_timeline.py -q` 通过；`frontend/npm run build` 通过。

限制与交接：

- 需由集成包在 `backend/main.py` 注册 `authoring.router`（建议 prefix `/api`），并在业务路由增加 `AuthoringPage`；本包未修改共享路由和数据库初始化。
- `MaterialWorkspace` 由材料包提供，TopicPage 的资料区嵌入应由集成时完成。
- 章节正文生成当前是确定性待补草稿，未调用模型；真实联网搜索需配置 Tavily 并另行验证。
- 请勿把章节作者审核状态解释为 `evidence_state=verified`。
