# 02 资料完整解析、来源留存与人工清洗实施计划

> **面向执行代理：** 实施时必须使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，按任务逐项执行；以下复选框仅用于将来记录实施进度。本次只编写计划，不修改业务代码、依赖和配置，不运行业务测试，不提交 Git，不启动实施代理。

**目标：** 建立不依赖向量化的项目资料库，保存原件和完整解析覆盖记录，经人工确认生成可追溯的数据版本，为选题和各章节提供有出处的候选输入。

**架构：** 原件、解析结果、清洗版本与可选向量索引分层保存。资料服务提供严格按项目与版本读取的证据接口；统一入口组件供数据页使用并由03包嵌入选题页，章节推荐与审核失效传播由相邻包消费版本事件实现。

**技术栈：** 沿用 FastAPI、Pydantic、SQLite、pypdf、python-docx、python-pptx、pandas/openpyxl、React/TypeScript、Ant Design、pytest、Vitest。OCR、渲染与视觉识别采用能力适配接口，具体依赖提交00/05统一确认和接入，不指定付费供应商，不在本包自行修改依赖清单。

**依据：** `docs/QCmaker修改需求汇总与规划.md` 第4章、5.2节、第7章、11.2—11.5节及11.7节；公共契约以00包冻结稿为准。

## 全局约束与实施入口

- 所有下述新增路径、表、类型、接口和状态均为**未来拟议设计**，不是已存在能力或用户已确认的最终界面。00未冻结前只能讨论差异，不能另建同名公共契约。
- “上传后直接读取，基本阅读不依赖向量化服务”；“长文档分批处理，不静默截断或遗漏”；“保留原始资料，派生文本和结构数据可追溯、可重建”。
- “AI先提出处理方案和差异预览，作者确认后应用”。人工允许继续写作不等于资料已经核实；格式整理确认也不改变事实来源性质。
- 取消的是参考资料上传固定10MB门槛。既有数据页10MB、5000行、200列、Excel展开40MB限制单独审视，不直接删除安全边界，不以截断伪装成功。
- 本包不实现联网检索、章节推荐算法、图表计算和成果审核；不将外部案例、模型推断或模拟数据转换为本项目已证实事实。
- 图片资料需进入支持矩阵；旧DOC/PPT只有经验证的转换能力才能宣布支持，未支持格式应明确拒绝。解析覆盖齐全不等于识别内容全部正确，必须保留质量问题和人工核验状态。

## 现状核查依据

以下为本次只读核查，不是测试结论：

| 当前文件/符号 | 实际情况 | 对应任务 |
|---|---|---|
| `backend/app/services/document_parser.py`：`MAX_TABLE_ROWS`、`_frame_documents`、`_csv_documents` | 表格最多保留1000行；CSV截断；DOCX正文和表格分开收集；PDF仅文本提取，空白/扫描页被丢弃 | M2 |
| 同文件 `_pptx_documents` | 已读取文字、表格和备注，但图片、图表含义和空幻灯片缺少覆盖记录 | M2 |
| `backend/app/api/endpoints/rag.py`：`ingest_document` | 一次读取10MiB+1，临时文件结束删除 | M1、M3 |
| `backend/app/services/rag.py`：`ingest_document`、`list_documents` | 原件未持久留存；入库、列表初始化向量服务；已有项目过滤、去重和旧集合隔离逻辑应保留 | M1、M5 |
| `backend/app/services/data_cleaning.py`：`parse_file` | 数据专用读取有5000行、200列及展开大小保护；Excel默认首表 | M4 |
| `backend/app/repositories/dataset_repository.py` | 已有原始值、当前值、revision、confirmed_revision；撤销恢复原始值，但不是完整历史版本库；数据到期机制存在 | M4 |
| `frontend/src/pages/DataPage.tsx` | 已有差异预览、确认和撤销，但只有一个dataRef，上传会替换当前关联 | M6 |
| `frontend/src/pages/TopicPage.tsx` | 存在参考资料10MB检查及文案，以切片条数展示资料；属于03独占 | 03集成M6 |

## 排他文件归属

以下路径相对项目根目录。一个文件只有本包执行者写入；本包内部任务顺序交接共用文件，不对同一文件并行写。

**修改既有文件（本包独占）：**

- `backend/app/services/document_parser.py`：格式解析、覆盖清单、兼容旧提取入口。
- `backend/app/services/rag.py`：可选索引，按项目/资料/版本过滤。
- `backend/app/services/data_cleaning.py`：纯预览运算、差异风险、单位及来源保留。
- `backend/app/api/endpoints/rag.py`：旧资料接口兼容适配。
- `backend/app/api/endpoints/data.py`：原数据接口版本确认及项目归属适配。
- `backend/app/repositories/dataset_repository.py`：在公共迁移基础上存储数据版本和关联。
- `frontend/src/pages/DataPage.tsx`：统一资料入口与多数据集选择，不覆盖已有项目资料。
- `frontend/src/api/data.ts`：既有数据接口适配。

**新增文件（未来拟议，本包独占）：**

- `backend/app/models/materials.py`：本域类型；从公共models/evidence.py导入EvidenceRef/EvidenceBlock。
- `backend/app/services/materials.py`：上传、作业恢复、清洗、证据解析和事件协调。
- `backend/app/services/material_recognition.py`：OCR/视觉/文档渲染能力协议及适配入口。
- `backend/app/repositories/material_repository.py`：资料记录、不可变版本、作业检查点、事件发件箱。
- `backend/app/api/endpoints/materials.py`：项目资料API。
- `frontend/src/types/materials.ts`、`frontend/src/api/materials.ts`：领域类型与API。
- `frontend/src/components/materials/MaterialWorkspace.tsx`、`ParseCoveragePanel.tsx`、`CleaningDiffPanel.tsx`：可嵌入资料入口、来源预览和清洗差异。
- `backend/tests/materials/conftest.py`：仅本目录夹具，生成文档样本、隔离文件库和OCR替身。
- `backend/tests/materials/test_material_repository.py`、`test_document_coverage.py`、`test_material_api.py`、`test_cleaning_versions.py`、`test_material_evidence.py`：分别对应M1—M5。
- `frontend/src/components/materials/MaterialWorkspace.test.tsx`、`CleaningDiffPanel.test.tsx`：M6验收。
- `docs/testing/materials-acceptance.md`：支持矩阵、真实样本人工核验与未支持能力记录。

**禁止本包改动：** `backend/app/models/contracts.py`、`backend/app/repositories/database.py`、`backend/main.py`、`frontend/src/types/api.ts`、`frontend/src/routes/router.tsx`、`frontend/src/context/*`、`frontend/src/storage/db.ts`、全部依赖清单及部署配置，由00/05独占；`TopicPage.tsx`由03独占。既有混合RAG/选题测试文件由05安排统一回归，本包只增加专属测试，避免与03冲突。

## 跨包接口与存储合同（00冻结后实施）

### 公共证据合同

```python
# 由00在公共models/evidence.py中定义，本包仅导入，其他包不得复制定义。
EvidenceRef = {
    "source_kind": "material|web|user|derived|simulation",
    "source_id": "string", "source_version": "positive integer",
    "locator": "string，例如PDF第23页表2第3行", "excerpt": "optional string",
    "origin_kind": "documented|user_reported|computed|hypothesis|simulation|pending",
}
EvidenceBlock = {"ref": EvidenceRef, "text": "string"}
# services/materials.py 提供同步、无模型调用的读取接口：
def list_evidence(project_id: str, source_ids: list[str]) -> list[EvidenceRef]: ...
def resolve_evidence(project_id: str, refs: list[EvidenceRef]) -> list[EvidenceBlock]: ...
```

本包只解析其拥有的material来源及登记到资料库的derived来源；web/user/simulation的生产和解析归公共分发器及相应包，不能返回空字符串掩盖不支持。空source_ids返回空列表，不隐式读取全项目。引用读取严格匹配project/material/version/locator；缺失与跨项目都返回404，旧版本可读，绝不自动换成最新版。相邻包消费完整EvidenceBlock或显式分页计划，不能把检索到3段等同通读材料。

### 本域类型与服务

`models/materials.py` 拟定义以下类型，其他任务引用同一类型，不复制：

- `MaterialVersion`：project_id、material_id、version（递增整数）、parent_version、original_sha256、original_path（仅服务端）、filename、size_bytes、created_at、parse_status、readiness、review_status。
- `ParseUnit`：unit_id、kind（page/slide/sheet/block）、ordinal、locator、expected_regions、regions、status、issues；region含region_id、kind（text/table/image/chart/notes/footnote/header/footer）、text、table_cells、bbox、method、confidence、status。分页后各单元必须可穷举。
- `ParseManifest`：material_id、version、units_total、units_completed、units_failed、units_pending、coverage_complete、readiness（unread/partial/readable/needs_review）、review_status（unreviewed/reviewed）、units、next_cursor。计数从全量清单计算，不从当前分页推断。
- `RecognitionResult`：regions、issues、method；能力接口`recognize(image_path: Path, *, language: str) -> RecognitionResult`及`render(source_path: Path) -> list[Path]`。无可用实现时抛`RECOGNITION_UNAVAILABLE`，不能返回空识别结果冒充成功。
- `CleaningOperation`：operation_id、category（document/data/evidence）、target_locator、before、after、reason、risk（low/high）、source_refs；`CleaningPreview`：preview_id、project_id、material_id、base_version、operations、diff_digest、expires_at；`CleaningReceipt`：version、parent_version、applied_operation_ids、event_id。
- `MaterialChangedEvent`：event_id、project_id、material_id、old_version、new_version、changed_locators、reason；公共事件信封由00冻结。03消费并定位待复核章节，04消费并定位待复核产物，05负责消费接线。
- 服务方法：`stream_original(project_id, filename, chunks)`（异步，chunks为AsyncIterator[bytes]，返回MaterialVersion）；`parse_material(project_id, material_id, version)`；`get_parse_manifest(project_id, material_id, version, cursor=None)`；`preview_cleaning(project_id, material_id, base_version, operations)`；`apply_cleaning(project_id, material_id, preview_id, diff_digest, confirmed_operation_ids)`；`undo_cleaning(project_id, material_id, base_version, restore_version)`。后五者为同步领域方法，API中将耗时工作交给受限工作线程。

### 拟议HTTP接口

统一前缀`/api/projects/{project_id}/materials`，所有接口沿用既有访问令牌校验；具体字段由00冻结：

| 方法/后缀 | 输入与输出 | 关键语义 |
|---|---|---|
| GET 根路径 | cursor → items、next_cursor | 不触发模型/向量调用 |
| POST 根路径 | multipart file；可选material_id、base_version；Idempotency-Key | 原件持久化成功返回202及material/version/parse_status；新上传默认新增资料，显式选择替换才创建同一资料新版本 |
| GET `/{material_id}/parse` | version必填，cursor可选 → ParseManifest | 全局计数及分页单元；可轮询进度 |
| GET `/{material_id}/original` | version必填 → 文件流 | 文件位置不外泄，安全下载文件名，拒绝跨项目 |
| POST `/{material_id}/parse/retry` | version、failed_unit_ids → 202作业状态 | 只重试失败/未完成单元；成功单元保留 |
| POST `/{material_id}/cleaning-preview` | base_version、operations → CleaningPreview | 无写入原值，无修改确认状态 |
| POST `/{material_id}/cleaning-apply` | preview_id、diff_digest、confirmed_operation_ids → CleaningReceipt | 服务端检查预览、风险确认和版本，事务创建新版本 |
| POST `/{material_id}/cleaning-undo` | base_version、restore_version → CleaningReceipt | 创建恢复版本，不删除历史 |

兼容旧`/api/rag/ingest`：继续返回document_id/filename/chunks供旧客户端过渡，新增material_id/version/readiness；chunks仅代表实际索引数量，无索引时为0。旧调用不因embedding缺失失败。旧`/api/data/*`继续可用，但接入新流程时必须传公共冻结的project_id及版本关联；未归属旧数据只允许明确迁移归属，不凭当前打开项目静默认领。

### 公共迁移交付给00/05

拟议表族：materials（项目资料注册）、material_versions（不可变版本）、material_parse_units（逐单元检查点）、material_cleaning_previews（预览摘要和有效期）、material_events（事务发件箱）；dataset历史版本和material/dataset关联由00统一建表。本包仓库在这些迁移完成后操作，不在仓库初始化函数偷偷建表。

- 外键和唯一键必须含project_id或经父表约束项目归属；作业检查点唯一键为project/material/version/unit。
- 文件存储使用`backend/data/materials/{project_id}/{material_id}/{version}/`的服务端生成ID目录，拒绝将用户文件名当路径；在测试中通过构造参数注入临时根目录。
- 原件先写`.part`、计算SHA-256、原子更名，再提交元数据；启动恢复清理无引用暂存文件，并识别“已有原件、未登记完成”的中断状态。失败不删除已有成功版本。
- 新资料持久保留策略与旧临时dataset TTL分开；已被引用数据不得被旧TTL清理器误删，05整合清理策略和测试。
- 旧Chroma切片可登记为`legacy_partial`、`original_missing`，沿用已有`__legacy_unassigned__`隔离；没有原件时不得补写“完整读取”。重新上传并校验来源后才形成新的可审阅版本。

## 依赖与并行调度

`00合同/迁移 → M1 → M3 → M4 → M5 → M6`；M2可在00冻结后与M1并行，M3接收M1和M2。03可先按MaterialWorkspace属性接口写替身，不改本包文件；04可先按EvidenceBlock和MaterialChangedEvent写替身。M4和M5都涉及materials服务，默认顺序交接。每个任务均以专属测试及可展示输出独立验收，整个包未完成不能宣称全量资料阅读达标。

## M1 原件流式存储与不可变资料版本

**文件：** 新建models/materials.py、repositories/material_repository.py、services/materials.py和tests/materials/conftest.py、test_material_repository.py（均加上前述目录前缀）。仅消费00迁移。

**输入/输出：** 输入项目ID、文件名、异步字节块；输出MaterialVersion。仓库提供`get_version(project_id, material_id, version)`、`list_versions(project_id, material_id)`、`save_original(...)`，服务不调用RAG。

- [ ] 编写隔离目录夹具和以下红灯测试；`stream_original`通过关键字`storage_root`构造所属`MaterialService`实例，模块级函数委托同一实例。

```python
import asyncio
from backend.app.services.materials import MaterialService

def test_large_original_survives_without_embeddings(tmp_path):
    service = MaterialService(storage_root=tmp_path)
    async def chunks():
        for _ in range(12):
            yield b"a" * (1024 * 1024)
    item = asyncio.run(service.stream_original("p1", "大资料.txt", chunks()))
    assert item.size_bytes == 12 * 1024 * 1024
    original = service.read_original("p1", item.material_id, item.version)
    assert original.stat().st_size == item.size_bytes
    assert item.readiness == "unread"
```

- [ ] 运行`python -m pytest backend/tests/materials/test_material_repository.py -q`，首次应因新增类型或服务不存在失败；禁止以真实用户资料库执行。
- [ ] 实现分块写入、hash、ID生成、原子更名和事务登记；补充`read_original(project_id, material_id, version) -> Path`仅供内部测试/下载使用。单次内存块建议1MiB，此值是I/O批次而非文件总量门槛。

```python
size = 0
with part_path.open("wb") as target:
    async for chunk in chunks:
        digest.update(chunk)
        size += len(chunk)
        target.write(chunk)
part_path.replace(final_path)
# 元数据登记异常时记录可恢复任务，原件不作为已提交资料暴露。
```

- [ ] 增加跨项目读取404、同文件名不覆盖、相同幂等键返回同版本、中途断连清理暂存、磁盘写失败、重启恢复用例；通过注入写入故障验证，不真正耗尽磁盘。
- [ ] 重跑专属测试并展示一份12MiB测试文件的原件hash与版本记录。交付文件清单和测试证据，不提交Git。

**独立验收：** 未配置任何模型时原件可保存、列出及按版本取回；失败无“上传成功”假状态。

## M2 全量解析、逐页覆盖与识别能力回退

**文件：** 修改services/document_parser.py；新增services/material_recognition.py、tests/materials/test_document_coverage.py、docs/testing/materials-acceptance.md；扩充M1本域类型时先交接所有权。

**输入/输出：** `parse_source(path: Path, filename: str, recognizer=None) -> ParseManifest`；保留`extract_documents`兼容适配，仅从完整清单派生文本，不删除清单中的空页和失败页。

- [ ] 写首个无截断红灯测试；另建含中文、合并单元格、页脚、图片、扫描页、PPT备注的生成型夹具，真实样本不复制进仓库。

```python
from backend.app.services.document_parser import parse_source

def test_csv_tail_is_not_lost(tmp_path):
    source = tmp_path / "台账.csv"
    source.write_text("序号,记录\n" + "\n".join(
        f"{i},巡检记录{i}" for i in range(1501)), encoding="utf-8")
    result = parse_source(source, source.name)
    text = "\n".join(r.text for u in result.units for r in u.regions)
    assert "巡检记录1500" in text
    assert result.coverage_complete
```

- [ ] 运行`python -m pytest backend/tests/materials/test_document_coverage.py -q`确认缺能力红灯。
- [ ] 将CSV/Excel的1000行截断改为全量分批迭代；遍历所有工作表、保持行列地址、合并关系、公式/缓存值区别。DOCX按XML块顺序遍历正文、表格、页眉页脚、注释/脚注和图片关系；不能提取的部分登记问题，不能忽略。PPT每页记录形状、备注、表格和图表；无需OCR的结构文字走直接解析。
- [ ] PDF先建立页数清单再解析；非空无文本、乱码或复杂布局进入渲染→OCR→可用视觉交叉核对；PNG/JPEG在识别能力可用时按单页资料处理。嵌入图片和图表登记区域，识别不可用则明确needs_review。未支持DOC/PPT返回明确格式错误及可用转换说明，禁止仅改扩展名。

```python
coverage_complete = (
    len(units) == units_total
    and all(unit.status in {"parsed", "verified_blank"} for unit in units)
    and all(region.status == "parsed" for unit in units for region in unit.regions)
)
# 非空页recognition不可用：保留页记录、issues和原页定位，coverage_complete=False。
```

- [ ] 加入扫描页不能当空白、OCR失败页号可见、中文字形乱码、PPT图表/备注、DOCX脚注、GB18030、复杂表格末行、工作簿多表覆盖和无OCR回退测试。`verified_blank`须经渲染/页对象覆盖检查，不能仅凭extract_text为空判定。
- [ ] 重跑专属测试；在验收文档记录各格式能力、未支持区域、页数核对、人工抽样与全文核验结果栏。20页12,905,586字节扫描标准、25页研究总结和35页QC样例是人工验收入口，缺文件或OCR能力须写“未执行/能力缺失”，不可代填通过。

**独立验收：** 覆盖清单与源文档全部页面/工作表/块一致，缺内容能精确定位；内容正确性须另经中文样本核对，不以confidence或切片数量替代。

## M3 项目资料API、进度与中断恢复

**文件：** 新建api/endpoints/materials.py、tests/materials/test_material_api.py；修改api/endpoints/rag.py、services/materials.py。主应用路由注册交05，本任务用局部FastAPI应用挂载router验收。

**输入/输出：** 消费M1原件服务与M2清单；产出前述上传、列表、原件、解析进度/重试接口。清洗路由于M4补齐。

- [ ] 用本目录夹具`materials_client`搭建仅包含本包router和现有错误处理的TestClient，不改backend/main.py。写未配置embedding仍可上传的测试。

```python
def test_upload_without_embedding_returns_accepted(materials_client):
    response = materials_client.post("/api/projects/p1/materials",
        files={"file": ("说明.txt", "中文说明".encode(), "text/plain")})
    assert response.status_code == 202
    item = response.json()
    listing = materials_client.get("/api/projects/p1/materials").json()
    assert item["material_id"] in {x["material_id"] for x in listing["items"]}
```

- [ ] 运行`python -m pytest backend/tests/materials/test_material_api.py -q`确认红灯。
- [ ] 实现上传流式迭代与202状态；解析作业持久化queued/running/partial/succeeded/failed，记录完成单元检查点。进程重启后running恢复为queued并从未完成单元开始，不能仅用无持久化的内存后台任务。

```python
async def upload_chunks(file):
    while chunk := await file.read(1024 * 1024):
        yield chunk
# router接收上传，服务先持久化original再排入持久化作业；原件完成前不返回202。
```

- [ ] 实现分页清单、版本必填、下载鉴权和重试幂等；更新旧rag上传适配，删除固定10MB检查。若资源不足返回明确507/资源不足码，解析超时保留检查点；不得删掉压缩炸弹、路径穿越、格式验证保护。
- [ ] 补充12MiB接口上传、重复retry不重复单元、下载项目隔离、密码PDF、损坏文档、并发上限与恢复测试；提交05核查代理上传体限制和请求超时清单，不擅自编辑部署文件。
- [ ] 重跑专属测试；展示上传进度（已发送字节）与解析进度（完成/总单元）分别表达，完成上传不代表完成解析。

**独立验收：** 中断恢复后没有缺页或重复版本，列表不访问向量服务；旧客户端可过渡，但索引条数不代表可读就绪。

## M4 人工清洗预览、明确确认及数据历史

**文件：** 修改services/data_cleaning.py、repositories/dataset_repository.py、api/endpoints/data.py、services/materials.py、api/endpoints/materials.py；新增tests/materials/test_cleaning_versions.py。

**输入/输出：** 消费M1不可变版本；产出CleaningPreview/CleaningReceipt和完整数据版本。三类操作都保留before/after/reason/source_refs；证据分析只提出支持、质疑和适用条件，不删除反向证据。

- [ ] 编写预览不修改来源、未确认不允许应用的测试；`cleaning_service`夹具用真实临时仓库，准备原值为"10%"的资料版本及对应locator，`percent_conversion`为action对应的CleaningOperation。

```python
import pytest
from backend.app.core.errors import AppException

def test_cleaning_requires_explicit_confirmation(cleaning_service, percent_conversion):
    service, material_id, version = cleaning_service
    preview = service.preview_cleaning("p1", material_id, version, [percent_conversion])
    assert preview.operations[0].before == "10%"
    assert preview.operations[0].after == 0.1
    with pytest.raises(AppException):
        service.apply_cleaning("p1", material_id, preview.preview_id,
                               preview.diff_digest, [])
    assert service.get_version("p1", material_id, version).version == version
```

- [ ] 运行`python -m pytest backend/tests/materials/test_cleaning_versions.py -q`确认红灯。
- [ ] 复用现有apply_rules纯拷贝运算，生成逐值差异。缺失填补、单位转换、数值变化、样本删除和结论变化一律high；AI只生成建议，缺模型仍可手动预览和清洗。转换后的数值仍引用原始位置，新增计算规则及derived来源，不改原文事实。
- [ ] 服务端持久化预览，校验preview_id、base_version、diff_digest、有效期和明确确认项；一次事务创建新版本和变化事件。低风险可批量确认；高风险必须在界面突出并提供明确确认，但不强制逐单元点击。重放同一已成功预览返回原receipt，不再生成版本。

```python
if current.version != preview.base_version:
    raise AppException("MATERIAL_VERSION_CONFLICT", "资料已变化，请重新预览", 409)
required = {operation.operation_id for operation in preview.operations}
if not required.issubset(set(confirmed_operation_ids)):
    raise AppException("CLEANING_CONFIRMATION_REQUIRED", "请确认本次变更", 422)
# 校验通过后以预览中存储的操作执行，不信任客户端提交的after值。
```

- [ ] 扩充dataset仓库为增量历史版本，保留已有raw/current/revision/confirmed_revision语义；撤销创建新版本，清空新版本确认状态。资料提取表格可选择为新数据集，不覆盖其他数据集；Excel默认首表行为改为显式选择已解析工作表。其他数据限制维持并明确说明，超界资料仍完整保留，可选择合法区域，不自动截取首5000行。
- [ ] 测试409冲突、摘要不符、预览过期、跨项目、撤销/重做可追溯、负面记录未静默删去、确认状态失效、旧原始值可读及多数据集并存；重跑专属测试。

**独立验收：** 未确认不能写入，改变规则需重新预览；新版本和被引用旧版本均可复现。

## M5 精确证据读取、可选检索与版本变化通知

**文件：** 修改services/materials.py、services/rag.py、repositories/material_repository.py；新增tests/materials/test_material_evidence.py。

**输入/输出：** 严格实现本计划前述list_evidence、resolve_evidence和MaterialChangedEvent；候选输入包含可引用文本、原始定位及来源性质。章节匹配算法及联网来源均在03。

- [ ] 写project与旧版本定位测试；`material_refs`夹具通过真实服务建立v1、v2，返回p1的v1引用，不能只模拟最终函数。

```python
import pytest
from backend.app.core.errors import AppException
from backend.app.services.materials import resolve_evidence

def test_ref_resolves_exact_version(material_refs):
    old_ref = material_refs[0]
    blocks = resolve_evidence("p1", [old_ref])
    assert blocks[0].ref.source_version == old_ref.source_version
    assert "估测" in blocks[0].text
    with pytest.raises(AppException):
        resolve_evidence("p2", [old_ref])
```

- [ ] 运行`python -m pytest backend/tests/materials/test_material_evidence.py -q`确认红灯。
- [ ] 实现按精确版本、页/表格单元定位取文，excerpt只用于展示不能充当唯一原文。原始文档里写的结论以documented表示“有文献记录”，不表示本项目真实性已经核实；估测、对照组、采样时间和单位作为上下文保留，缺项显式可见。
- [ ] 索引由清单派生并记录project_id/material_id/version/unit_id。仅可选后台建立向量；无embedding时采用已保存文本的关键词检索或按来源阅读，结果明确retrieval_method，不能声称完成向量检索。完整阅读应遍历全部清单单元，不由top-k决定。

```python
# 不用文件名定位，不将旧引用升级到最新版本。
version = repository.get_version(project_id, ref.source_id, ref.source_version)
region = repository.get_region(project_id, version, ref.locator)
return EvidenceBlock(ref=ref, text=region.text)
```

- [ ] 事务发件箱保存变化事件，提供`pending_events(project_id) -> list[MaterialChangedEvent]`和`ack_event(project_id, event_id)`；05接线到03章节和04产物失效服务，消费者按event_id幂等处理，失败重试。事件只提示受影响引用，不要求整个项目重来。
- [ ] 加入无模型读取、索引失败不影响阅读、旧版本引用、版本事件重试、外项目资料拒绝、legacy_partial不冒充完整、相同资料跨章复用的测试；用研究总结337.04/374.29“对照/处理估测”文本夹具验证语义保留，不将该数值改为前后实测。

**独立验收：** 03/04可用两个公共接口取得精确来源；新增资料不删除旧资料，版本变化事件可重放、可定位。

## M6 统一资料组件、解析预览和人工确认界面

**文件：** 新增frontend/src/types/materials.ts、api/materials.ts、三个components/materials组件及两份测试；修改pages/DataPage.tsx、api/data.ts。不得修改TopicPage、router、context或storage。

**输入/输出：** `MaterialWorkspace({projectId: string, onSourcesChanged?: (sourceIds: string[]) => void})`。组件自取资料列表，提供进度、原件下载、版本选择、解析区域定位和清洗入口；不要求Excel先就绪。DataPage保留既有数据处理入口，新资料组件与数据集选择互不覆盖。

- [ ] 写组件红灯测试。Mock api/materials中的uploadMaterial/listMaterials/getParseManifest等真实导出函数，返回完整状态；测试不真实上传或调用模型。

```tsx
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ParseCoveragePanel } from './ParseCoveragePanel'

it('显示未识别页且不宣称读取完整', () => {
  render(<ParseCoveragePanel manifest={{ material_id: 'm1', version: 1,
    units_total: 20, units_completed: 19, units_failed: 1, units_pending: 0,
    coverage_complete: false, readiness: 'needs_review', review_status: 'unreviewed',
    units: [], next_cursor: null }} />)
  expect(screen.getByText('19 / 20')).toBeInTheDocument()
  expect(screen.getByText(/仍有未完整解析内容/)).toBeInTheDocument()
  expect(screen.queryByText('全部读取正确')).not.toBeInTheDocument()
})
```

- [ ] 在frontend目录运行`npm test -- src/components/materials/MaterialWorkspace.test.tsx src/components/materials/CleaningDiffPanel.test.tsx`确认红灯；ParseCoveragePanel测试放在MaterialWorkspace.test.tsx中。
- [ ] 实现有界列表分页、版本选择、上传字节进度、解析单元进度及异常页定位；图片与原文并列核对。切换projectId时取消旧请求或忽略旧响应，不能把上一项目结果写入新项目。移除本组件参考资料10MB限制，不展示“支持任意文件”。
- [ ] 实现CleaningDiffPanel的分类、前后值、风险、理由和确认；预览签名变化即禁用应用按钮，409后保留用户规则但重新预览。清洗完成回调通知来源更新，不自动确认相关章节。

```tsx
const canApply = preview !== null
  && preview.base_version === selectedVersion
  && preview.operations.every(op => confirmedIds.includes(op.operation_id))
return <Button disabled={!canApply || busy} onClick={applyPreview}>确认并应用</Button>
```

- [ ] DataPage加入资料入口和多数据集选择，既有纯数据上传的10MB说明维持独立显示。发送03嵌入说明：以MaterialWorkspace替换旧上传区域，删除TopicPage内10MB判断、≤10MB文案及“段数=阅读范围”表现。发送05需要的公共context接口及多数据集持久化接线差异，不直接修改共享文件。
- [ ] 补齐12MiB参考资料选择成功、旧项目异步响应隔离、无OCR提示、未确认不能应用、刷新恢复版本状态、多数据集不覆盖测试；在frontend目录重跑指定测试和`npm run build`。构建若因其他包未集成失败，记录具体依赖，不宣称本包端到端通过。

**独立验收：** 数据页无需Excel可浏览辅助资料，用户能判断读了哪些页、哪些区域未读、哪些值将改变；03可独立嵌入组件。

## 错误、恢复与迁移验收表

| 情形 | 返回/呈现 | 恢复与不变条件 |
|---|---|---|
| 上传中断、磁盘不足 | 上传失败原因、原件未成功标志 | 清理暂存；原成功版本不变，重新上传可幂等恢复 |
| 不支持格式、加密或损坏文档 | 格式/密码/损坏分别解释 | 原件保留（已成功上传时），支持重新解析或重新提交，不能标已读 |
| OCR不可用或低质量 | 失败页、region、所需能力 | 可重试可用适配器或人工核验，不用模型猜补 |
| 向量化失败 | 索引不可用而资料可读 | 重建索引不重写原件、版本及确认记录 |
| 清洗过期/并发修改 | 409版本冲突或预览失效 | 重新计算预览后再次确认，禁止覆盖新版本 |
| 引用的旧原件缺失 | original_missing/readiness partial | 提示补原件，保持旧引用记录，不用切片重构伪原件 |
| 事件消费失败 | 待处理事件保留 | 按event_id重放，消费者幂等；不能先删事件再更新章节 |
| 老dataset到期 | 已引用记录不得静默删除 | 00/05迁移持久引用和保留策略；未归属数据单独隔离 |

## 最终交付清单与包间移交

- [ ] 交付排他文件清单、六项任务测试记录、支持格式/识别能力矩阵与明确未支持范围。
- [ ] 交付原件hash核验、覆盖清单、失败页重试证据；真实中文样本逐页/逐表核对另附记录，不以单元测试替代。
- [ ] 交付预览确认、撤销、项目隔离、版本一致性与事件幂等证据；保留旧数据版本能力，不能回退为单一当前值。
- [ ] 向00/05提交表迁移、路由注册、存储保留、部署上传限制、OCR依赖接线请求；向03提交组件与无embedding读取接口；向04提交精确EvidenceBlock及版本事件。
- [ ] 由05执行已有RAG、安全隔离、管理清理及数据页面回归，确认兼容失败有明确迁移处理。未接完共享接线、未做真实文档核对时，本包状态应为“局部通过/待集成”，不可标“全部内容读取正确”。

本计划只拆解后续实施工作，以上复选框保持未完成；未执行所列命令，未改变现有应用行为。
