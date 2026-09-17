# 公共约定与并发前置条件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先固定跨包数据含义、接口和文件负责人，避免并发实现后无法衔接。
**Architecture:** 独立领域模块共享最小证据与版本约定；公共文件集中修改，领域包提供迁移定义，由集成者统一登记。
**Tech Stack:** 现有 FastAPI、Pydantic、SQLite、React、TypeScript、IndexedDB。
**Spec:** [需求总纲](../../../QCmaker修改需求汇总与规划.md)，重点为4.4—4.5、5.2、7.3—7.7及11.3。

## Global Constraints

- 当前只整理文档，以下均为未来实施步骤，勾选项不代表已完成。
- 本文字段及接口为建议工程契约，实施时由协调者完成C0冻结后再分发。业务含义不能由各包自行改动。
- 不更改标准原文解读，不把作者审核、联网参考或模拟值升级为项目实测事实。
- 所有相对代码路径以项目根目录为准；新增文件、表、测试及接口均为拟议设计。

## 1. 文件所有权

本包由协调者串行执行，负责新增 `backend/app/models/evidence.py`、`frontend/src/types/evidence.ts`，以及公共契约样例 `backend/tests/fixtures/qc_contracts/`。01—04包只读这些文件。

下列现有共享文件只允许协调者在00前置或05集成时修改：

- `backend/app/models/contracts.py`、`backend/app/repositories/database.py`、`backend/main.py`。
- `frontend/src/types/api.ts`、`frontend/src/api/client.ts`、`frontend/src/api/insight.ts`。
- `frontend/src/context/`、`frontend/src/storage/db.ts`、`frontend/src/hooks/useWizardGuard.ts`、`frontend/src/layouts/WizardLayout.tsx`、`frontend/src/routes/router.tsx`。
- 公共测试夹具 `backend/tests/conftest.py`、前端测试setup、依赖清单和锁文件、部署配置及全局样式。

领域表结构由领域包声明需求，不允许仓库类自行在导入时建表；数据库版本及执行顺序只有一处登记。

## 2. 必须一致的数据含义

| 对象 | 最小约定 | 生产者 → 消费者 |
|---|---|---|
| EvidenceRef | `source_kind: material/web/user/derived/simulation`；`source_id`；`source_version`正整数；`locator`字符串；`excerpt`可选；`origin_kind: documented/user_reported/computed/hypothesis/simulation/pending` | 02资料、03检索及编写 → 03、04 |
| EvidenceBlock | `{ref: EvidenceRef, text: string}`；保留结构化表格位置，不把摘要冒充全文 | 02 → 03 |
| ProjectContext | 项目ID、地域、业务环境、人员及设备约束、活动时间范围、课题类型、目标来源、标准版本、来源说明、revision | 03 → 02推荐、04导出 |
| MetricSpec | metric_id、名称、单位、分子/分母、对象、比较方式、采样方法、时间范围、估测/实测/模拟性质、refs | 03；02提供候选 → 04 |
| ChapterSnapshot | 项目、chapter_id、revision、路径版本、正文块、指标、证据引用、三类状态、上游版本清单 | 03 → 04 |
| ArtifactSnapshot | 图表或导出ID、项目、内容版本、上游版本清单、生成时间、标识、失效原因 | 04 → 03/05 |

`documented`仅表示资料中确有记载，不等于项目事实已核实；`computed`保留公式和输入引用，计算不能提高输入真实性。source_version与章节revision均独立递增，跨项目引用必须拒绝。locator建议采用可显示字符串，如“PDF第23页表2第3行”；结构化定位扩展在本约定之外另行冻结，不能各包使用互不兼容的对象替代字符串。

### 三类状态与失效

- `content_state: empty/draft/complete`：章节内容形成情况。
- `review_state: pending/approved/changes_requested`：作者是否接受这一版表达。
- `evidence_state: missing/partial/verified/not_applicable`：证据核对情况。verified须有核对人、时间、依据；不适用须说明理由。
- `stale: boolean`及`stale_reasons[]`单独表示上游变化；不删除旧快照，不把已审核旧版当作新版已审核。
- 简单文本可以快速或批量审核；关键指标、要因判定、实施效果和真实性变化必须逐项显示差异。允许接受草稿并继续，不能通过“继续”把evidence_state改为verified。

### 版本与请求

所有修改请求校验预期版本；章节及配置使用`expected_revision`，资料使用`base_version`，清洗应用使用preview_id绑定的base_version，不能省略并发检查。冲突返回HTTP 409及当前版本。重复生成携带`operation_id`，资料上传和清洗应用使用`Idempotency-Key`（清洗应用亦可采用唯一preview_id加操作集摘要作为幂等键），相同操作不得重复计费或重复应用；领域层的CleaningOperation.operation_id仅标识单条清洗动作，不能混作整次请求ID。长任务返回任务状态，完成结果仍校验输入版本；旧结果保留历史，不覆盖新内容。身份认证沿用现有边界，不因新增project_id就默认允许读取该项目。

## 3. 对接面

| 提供包 | 拟议对接面 | 约束 |
|---|---|---|
| 01 | 角色能力解析与配置快照；连接验证结果 | 03显式传`topic`等角色；不直接读取密钥 |
| 02 | `list_evidence(project_id, source_ids) -> list[EvidenceRef]`；`resolve_evidence(project_id, refs) -> list[EvidenceBlock]` | 不以RAG命中数量声称全文已读；校验来源版本 |
| 02 | `MaterialWorkspace(projectId, onSourcesChanged)` | 03嵌入；上传、解析、清洗交互由02维护 |
| 03 | `GET /api/projects/{project_id}/chapters/{chapter_id}/snapshot?revision=N` | 04只消费不可变快照；不能直接解析聊天记录当阶段数据 |
| 03 | `POST /api/search/test`及带状态的检索结果 | 01展示结果；not_configured/failed/empty/success分开 |
| 04 | 图表、导出结果包含输入版本及失效信息 | 05将结果纳入项目恢复和下游提示 |

02仅解析material及其登记的derived来源；web/user/simulation由03的来源解析入口分发并解析，03遇material时委托02。缺失和跨项目引用均返回404，不返回空文本掩盖问题。MaterialChangedEvent含event_id、project_id、material_id、old_version、new_version、changed_locators、reason；03更新章节依赖，04更新产物依赖，05负责消费接线和幂等重试。

02资料路由：`GET/POST /api/projects/{project_id}/materials`；单份资料下`GET /parse`、`GET /original?version=N`、`POST /parse/retry`、`POST /cleaning-preview`、`POST /cleaning-apply`、`POST /cleaning-undo`。所有操作必须遵循项目隔离及原始版本保留规则，路由最终注册由05处理。

## 4. C0冻结步骤

- [ ] **C0.1 核对基础**：记录实施时Git版本及工作区改动；核对原有API、安全、计费及版本机制；不得把本文静态观察当作实施时现状。
- [ ] **C0.2 固定公共模型**：实现并审阅上述证据、状态、版本最小类型；各包专有字段置于各自models/types文件。输出有效、冲突、缺证据、模拟四组JSON契约样例。
- [ ] **C0.3 冻结角色与检索签名**：与01/03对齐配置快照、搜索草稿测试参数和结果字段；禁传明文密钥到日志或浏览器返回体。01/03文档中的专有接口在此登记后才可并行。
- [ ] **C0.4 冻结迁移清单**：01提交profiles/credentials需要的表；02提交materials/material_versions/material_parse_units/material_cleaning_previews/material_events及数据集版本历史；03提交项目场景、章节、审核、来源依赖和活动记录；04提交图表/导出版本元数据。协调者统一命名与外键、索引、清理策略。
- [ ] **C0.5 提供可运行基础**：完成测试库初始化及领域空仓库需要的迁移注册，前后端契约样例可验证；公共基础落稳后再放行并发。不能让领域包各自改database.py以绕过依赖。

现有database.py把业务和管理端DDL合并计算v1校验和。不得直接向原v1脚本追加新表造成旧库校验失败；保留原v1内容和校验和，引入后续版本及事务迁移。05负责存量库迁移、故障恢复及最终回归；00负责让开发/测试基础可用。

建议契约测试（拟新增`backend/tests/test_qc_shared_contracts.py`）：

```python
def test_review_does_not_verify_evidence():
    chapter = chapter_fixture(content_state="complete", evidence_state="partial")
    approved = approve_fixture(chapter)
    assert approved.review_state == "approved"
    assert approved.evidence_state == "partial"
```

fixture为实施时新增测试辅助函数，不是现有API。运行目标：`python -m pytest backend/tests/test_qc_shared_contracts.py -q`；前端增加对应枚举和往返样例检查。

## 5. 放行与变更规则

C0只有在公共类型、接口样例、表清单、文件归属和错误语义都已冻结并验证后通过。其后改契约时，提出“原因、受影响包、兼容方式、样例差异”，由协调者一次修改并通知所有消费者；暂停受影响任务，未受影响任务可继续。不得以各自增加可选字段掩盖同名不同义。

本次文档交付状态：**设计草案完成后可供实施评审；C0尚未执行，未授权启动代码工作。**
