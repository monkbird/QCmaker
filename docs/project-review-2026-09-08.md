# QCmaker 项目审查报告

> 本文为修复前的历史审查记录。后续处理及验收结果见 [修复记录](review-fixes-2026-09-09.md)。

审查日期：2026-09-08。范围：当前工作目录的前后端业务代码、状态持久化、接口契约、安全措施、模型调用、文件生成及已有测试。此次未修改业务代码，未读取或输出真实密钥，未主动调用真实付费模型。运行了已有测试、构建及若干离线边界验证。报告中的数字为实际检查结果。

## 总体判断

项目可以构建，现有单元测试通过，但不能据此认定六步业务流程可靠。最需要优先解决的是：新上传数据无法正确通过路由门禁、数据列静默覆盖、预览与应用不一致、旧成果重新恢复、启用鉴权后无法下载，以及模型调用的费用和脱敏边界不完整。

以下共列出 34 个问题条目。P1 表示优先修复（流程阻断、数据错误或明显安全问题）；P2 表示正常迭代应解决；P3 表示质量、体验或维护改进。证据标注“已复现”为本次运行验证，“代码确认”为调用链和实现直接可见，“条件风险”为需要特定运行条件才能触发。

## 实际检查结果

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| `.venv/Scripts/python.exe -m pytest -q` | 55 passed | 1 条 LangChain Community 弃用警告 |
| `npm.cmd test` | 5 passed / 3 files | 覆盖面较窄 |
| `npm.cmd run lint` | 通过 | 不代表业务流程正确 |
| `npm.cmd run build` | 通过 | 图表页面 JS 约 1152.87 kB，gzip 388.52 kB；主入口约 681.72 kB |
| `npm.cmd exec playwright test` | 1 failed | 旧标题定位器与实际页面不一致 |
| 补充离线验证 | 复现多个缺陷 | 包括 reducer 版本字段、重复列、百分比、布尔推断、异常响应、出站地址、代理头及图表轴校验 |

未进行真实供应商连通性、真实模型结果质量、长时间负载、完整人工交互和所有 PPT 模板的视觉验收。安全结论为代码层审查，不等于完成渗透测试。

## 业务流程与数据一致性

### 01. P1：上传成功后向导数据版本仍为空，确认后被退回数据页

- 位置：`frontend/src/context/wizardReducer.ts:9`；`frontend/src/hooks/useWizardGuard.ts:2`。
- 证据：已复现。`SET_DATA_REF` 的 payload 是 `{dataRef, revision}`，直接展开后写入了额外的 `revision` 字段，没有更新状态中真正使用的 `datasetRevision`。
- 最小验证输出：`{"dataRef":"d1","datasetRevision":null,"unexpectedRevision":0}`。
- 影响：新项目上传并确认数据后，门禁仍判断 `datasetRevision===null`，进入研讨时被送回数据页。已有项目还会保留旧版本号，导致下游失效判断错误。
- 建议：显式映射 `datasetRevision: action.payload.revision`，补上传→确认→进入研讨的完整测试。

### 02. P1：上游变化后，旧纪要、旧图表及旧 PPT 可在刷新后重新出现

- 位置：`frontend/src/context/WizardContext.tsx`，`persistProject`、`setTopic`、`storeDataset` 和初始化恢复逻辑。
- 证据：代码确认；`null` 清空语义已单独复现。`next.chartOption ?? state.chartOption` 会把主动传入的 `null` 当作“未传值”，继续保存旧成果。
- 此外，修改课题、修改数据只清理 reducer，未同步清理 `project_state`。恢复时又从这个旧记录直接读取成果。
- 影响：界面当时显示已清空，刷新后却再次带入旧课题或旧版本成果，可能形成图文不一致的报告。
- 建议：区分 `undefined` 与 `null`；所有上游变更统一、原子地清理持久层；成果记录关联课题、数据集 ID 和 revision。

### 03. P2：恢复只更新远端版本号，不更新本地数据内容

- 位置：`frontend/src/context/WizardContext.tsx` 初始化中的 `getDataset`；`frontend/src/pages/DataPage.tsx`、`VisualizationPage.tsx` 中的 `loadDataset`。
- 证据：代码确认。远端获取成功后只写 `datasetRevision`、`dataConfirmed`，没有将远端 rows、columns、report、revision 回写 IndexedDB。
- 触发：另一个标签页或 API 修改数据后刷新当前项目。
- 影响：向导认为当前版本已经确认，数据页和图表页仍使用旧本地版本，显示旧内容并反复得到 409。
- 建议：完整同步远端 DatasetResponse，并根据 revision 变化清理下游成果；远端不可用时显式展示离线状态。

### 04. P1：应用的规则不一定是用户刚刚预览的规则

- 位置：`frontend/src/pages/DataPage.tsx`，`doPreview`、`apply`、勾选框和 AI 建议选择逻辑。
- 证据：代码确认。预览只保存 `preview_rows`；之后勾选规则或采纳 AI 建议不会清空预览；应用时重新读取当前 `rules`。
- 复现步骤：预览规则 A→改选规则 B→点击“应用预览规则”。页面展示 A 的结果，后端执行 B。
- 影响：用户依据错误预览批准数据改动。
- 建议：保存预览对应的规则快照和 base revision；任何规则修改立即作废预览；应用时只提交快照。

### 05. P2：撤销后仍显示旧预览，选择项也可能错位

- 位置：`frontend/src/pages/DataPage.tsx`，`undo`。
- 证据：代码确认。撤销没有 `setPreview(null)` 和 `setSelected([])`，而应用清洗和上传时做了这些清理。
- 影响：数据已恢复原始版本，表格仍展示上一次预览；旧检测项索引可能指向新报告中的另一个问题。
- 建议：撤销后清理所有派生状态，并为撤销设置 busy 防止重复提交。

### 06. P2：最多支持 5000 行，界面却只能查看前 200 行

- 位置：`frontend/src/pages/DataPage.tsx`，`dataSource={displayed.slice(0,200)}`、`pagination={false}`。
- 证据：代码确认。
- 影响：第 201 行之后无法翻页或查看，但清洗和确认作用于全部数据。用户无法核验后部异常。
- 建议：增加分页或虚拟表格，并支持从检测项跳转对应行；明确区分预览行数与总行数。

### 07. P1：列名去空格后重名，原始列被静默覆盖

- 位置：`backend/app/services/data_cleaning.py:38` 及 `rows_from_frame`。
- 证据：已复现。CSV ` A,A \n1,2\n` 解析后两列都叫 `A`，构造字典只保留 `{'A':'2'}`，没有任何问题提示。
- 影响：真实数据在上传阶段即丢失；后续统计、图表和成果均可能错误。
- 建议：规范化列名后检查唯一性，拒绝冲突或生成稳定的唯一列名，并返回重命名说明。

### 08. P1：百分比列可被推荐为数值轴，却没有可用的前端清洗入口

- 位置：`backend/app/services/data_cleaning.py:63`；`backend/app/services/chart.py`；`frontend/src/pages/DataPage.tsx`。
- 证据：已复现。上传 `90%`、`80%` 得到 percent 列，但检测问题列表为空；图表生成返回 `DATA_Y_NOT_NUMERIC`。
- 原因：`analyze` 从未产生 `type_conversion` 检测项；前端只能对已有问题选择规则。后端虽然有 `convert_percent`，正常界面无法使用。
- 影响：常见合格率、完成率数据无法走通制图；报错提示的 `convert_number` 也无法直接处理 `%`。
- 建议：提供明确的百分比转换问题和动作；统一百分比存储单位、展示单位及图表格式。

### 09. P2：布尔列被推断成数值列

- 位置：`backend/app/services/data_cleaning.py:63`。
- 证据：已复现，单列 `True` 的推断结果是 `number`。数值判断位于布尔判断之前，Pandas 将布尔视作可转换数值。
- 影响：推荐逻辑把“是否合格”当作普通数值，但图表随后用 `float('True')` 解析失败。
- 建议：先判断布尔，再判断数值；明确布尔字段采用分类还是计数统计。

### 10. P2：损坏文件和空文件返回内部错误，体积限制也没有约束解析成本

- 位置：`backend/app/services/data_cleaning.py:27`；`backend/app/api/endpoints/data.py`，`upload_data`。
- 证据：空 CSV 已复现 `EmptyDataError`，代码没有转换为业务异常；损坏 Excel 同样缺少解析异常封装。
- 条件风险：async 上传接口内直接执行同步 Pandas 解析、逐行转换和分析；完整解析后才检查 5000 行/200 列。压缩后的 Excel 较小不代表解析后的内存较小。
- 影响：坏文件得到 500；较重解析可能阻塞事件循环、研讨消息及心跳。
- 建议：解析异常统一返回格式错误；在线程执行解析；读取时限制行数，并约束解压体积和处理耗时。

## 研讨、选题与知识库

### 11. P1：数据分析师实际上没有收到数据值

- 位置：`frontend/src/pages/DiscussionPage.tsx`；`backend/app/services/discussion_session.py`，start 状态和 context 构造。
- 证据：代码确认。前端仅发送“共几行、几列、字段名”，后端不接收 dataset_id/revision，也没有从数据库读取实际 rows。
- 影响：即使上传真实数据，研讨也无法计算合格率、比较前后变化或核验根因；不同数值但相同结构的数据会得到同样的数据上下文。
- 另一个竞态：本地数据摘要异步加载，WebSocket 可先以默认“已确认数据”启动。
- 建议：后端根据已确认数据集和版本生成统计摘要、适量样本及质量信息，研讨记录绑定数据版本。

### 12. P2：可恢复错误没有真正触发恢复，重连耗尽后缺少重试入口

- 位置：`frontend/src/hooks/useDiscussionSocket.ts`；`frontend/src/pages/DiscussionPage.tsx`。
- 证据：代码确认。收到 `recoverable:true` 只设置 `needRecover`，不关闭连接、不切换 failed、不展示错误；recover 仅在下次 onopen 才发送。
- 同时，`attempt>5` 直接停止连接，但状态仍可能是 reconnecting；页面仅 failed 时显示“重新连接”。
- 影响：模型暂时失败后用户看不到原因，失败轮次没有自动恢复；网络连续故障后界面可能永远停在重连中。
- 建议：建立明确的错误/恢复状态；提供恢复当前轮次按钮；耗尽次数后置 failed；管理和清理重连定时器。

### 13. P2：已结束会话刷新后可能显示仍连接，并允许再次结束

- 位置：`frontend/src/hooks/useDiscussionSocket.ts`；`backend/app/services/discussion_session.py`，resume。
- 证据：代码确认。hook 的 finished ref 重建后为 false；加载本地 finished 事件只更新列表。resume 从已保存 lastEventSeq 之后回放，因此可能只收到新 ack，看不到之前的 finished。
- 影响：界面显示 connected，继续发送会触发“当前会话已经结束”的协议错误。
- 建议：恢复本地事件时恢复终态；resume 响应携带会话状态快照。

### 14. P2：专家发言整轮完成后才发送，长轮次期间页面像没有响应

- 位置：`backend/app/api/endpoints/discussion.py`，`for event in await execute(command)`；`backend/app/services/discussion_session.py`，outputs。
- 证据：代码确认。事件虽逐条入库，但 accumulate 到列表后才交给 WebSocket 发送。
- 影响：主持人已经完成发言，前端仍然看不到；“结束研讨”命令也要等当前 execute 完成才能被读取，无法中止正在运行的轮次。
- 建议：事件通过异步迭代或队列立即输出，接收命令与执行分离；明确区分“结束并生成纪要”和“取消当前轮次”。

### 15. P2：多个连接恢复同一会话时存在重复执行命令风险

- 位置：`backend/app/services/discussion_session.py:78`、`:103` 及 `_execute_locked`。
- 证据：条件风险，未进行并发压测。多个连接可能各自取得同一份 pending/running 列表；后一个获得租约后，更新命令状态的 SQL 即使影响 0 行，仍继续执行，没有确认命令是否已经 completed。
- 影响：恢复 finish 命令时尤其可能再次调用撰稿模型、再次产生 finished 事件和费用。角色完成标记只覆盖部分操作，不能替代命令级领取。
- 建议：获得租约后原子核验并领取命令；completed 立即跳过；在数据库层约束终态幂等。

### 16. P2：选题长对话会超出后端历史限制，失败消息还会继续堆积

- 位置：`frontend/src/pages/TopicPage.tsx`；`frontend/src/api/topic.ts`；`backend/app/models/contracts.py:78`。
- 证据：代码确认。前端发送完整 history，不裁剪；后端限制 50 条。一问一答累计到 52 条后，后续提交必然 422。
- 补充问题：Enter 发送不检查 busy，可并发触发；请求失败后已经加入本地的用户消息也不回滚。并发响应基于旧 history 覆盖，可能丢消息。
- 建议：按条数和 token 双重裁剪历史，限制并发发送，并为失败消息提供明确重试状态。

### 17. P1：知识库 embedding 输入未经过脱敏

- 位置：`backend/app/services/rag.py:59`、`:73`；对照 `backend/app/core/llm_gateway.py`。
- 证据：代码确认。文档切片直接 `add_documents`，检索 query 直接 `similarity_search`。脱敏只在 chat 网关中执行。
- 影响：启用外部 embedding 后，上传材料中的手机号、身份证、邮箱等可能原样发送到服务商；不能认为 chat 脱敏覆盖了全部模型输入。
- 建议：embedding 也使用统一脱敏网关，保留必要的本地映射；明确原文存储及向外发送范围。

### 18. P2：知识库检索调用 embedding 不受预算预留与熔断限制

- 位置：`backend/app/services/rag.py:73`；`backend/app/api/endpoints/topic.py` 中 `_search_references`。
- 证据：代码确认。文档入库走了 reserve_embedding，查询向量化却直接调用 similarity_search。
- 影响：预算耗尽后仍可通过检索产生外部 embedding 调用；选题先检索后 chat，可能已经产生费用才被聊天预算拦截。
- 建议：将 embed_documents 和 embed_query 都封装到预算客户端；使用同一个 request_id 完成预留、调用和结算。

### 19. P2：删除资料标签并未删除知识库内容，项目之间也没有资料隔离

- 位置：`frontend/src/pages/TopicPage.tsx`，资料 Tag 的 onClose；`backend/app/api/endpoints/rag.py`；`backend/app/services/rag.py`。
- 证据：代码确认。关闭标签只更新 materials；无删除 API，返回的 document_id 也没有与向量 ID 持久关联。集合按模型配置划分，没有 project_id 过滤。
- 影响：用户认为已移除的资料仍参与后续选题；同服务端不同课题可能相互引用旧材料；重复上传会继续追加切片。
- 建议：提供文档注册表、向量 ID 映射、真实删除和项目过滤；若有意使用全局库，应显式标明。

### 20. P2：仅轮换 API Key，也会让历史知识库看起来丢失

- 位置：`backend/app/services/rag.py:17`。
- 证据：代码确认。collection fingerprint 包含 secret，API Key 一变就选择新集合。
- 影响：相同 embedding 模型和地址下，仅更换密钥也无法检索原集合，用户可能反复上传、重复付费。
- 建议：向量空间身份由模型、维度及必要端点参数决定；凭据轮换只重建客户端。若用密钥作为租户边界，应采用显式且可迁移的租户标识。

## 安全、鉴权与费用

### 21. P1：PPT 下载未携带访问令牌，开启鉴权后下载必然失败

- 位置：`frontend/src/api/ppt.ts:5`；`frontend/src/pages/PPTPage.tsx`；`backend/app/api/endpoints/ppt.py`。
- 证据：代码确认。下载使用普通 href；axios 配置的 `x-api-token` 不会自动加入浏览器链接请求，URL 也未携带 token。
- 影响：生成成功，但下载得到 401。
- 建议：使用带鉴权头的 API 请求下载 Blob，再触发本地保存，避免把长期 token 放进 URL。

### 22. P1：限流信任任意 X-Forwarded-For，可更换伪造值绕过

- 位置：`backend/app/core/security.py:79`。
- 证据：已复现。同一连接设置 `X-Forwarded-For: fake-client`，限流键即变成 fake-client。
- 影响：直接访问后端或代理未覆盖该头时，攻击者可不断更换头部获得新额度。
- 建议：只信任已配置的代理，优先使用由可信代理链解析后的地址。另需为 WebSocket 单独设置连接及消息频率限制，HTTP middleware 不覆盖它。

### 23. P1：SSRF 防护只检查主机名文本，不核验解析出的 IP

- 位置：`backend/app/core/security.py:105`、`:114`。
- 证据：已复现校验接受 `http://127.1:8000`；任意非 IP 主机名也直接通过。是否真正连接到环回取决于后续客户端和系统解析，当前检查没有覆盖。
- 影响：解析到内网的域名、不标准 IP 写法可能绕过“外部模型禁止内网”的约束；DNS 重绑定同样没有防护。
- 建议：规范化地址，验证解析结果并把验证与实际连接绑定；控制重定向和出站网络权限。本地模型访问内网应采用明确的允许目标。

### 24. P1：任意测试地址可接收服务器已保存的供应商密钥

- 位置：`backend/app/api/endpoints/config.py`，`models` 和 `check_connectivity`。
- 证据：代码确认，未实际向外发送密钥。用户可提交任意公网 base_url，省略 api_key 时后端回退到已保存 key，并把它放入请求头发送给该地址。
- 触发前提：调用者能够访问配置接口；默认未设置 API_ACCESS_TOKEN 时该接口不要求令牌；设置后所有持有同一 token 的客户端也具有相同配置权限。
- 影响：原本不直接返回给前端的服务商 key，可被转发到调用者控制的公网主机。
- 建议：存储凭据绑定经过确认的服务地址；目标变更要求显式提供对应凭据；将配置管理权限与普通业务调用分开。

### 25. P1：预算按输出上限预留，但真实聊天请求没有设置该上限

- 位置：`backend/app/services/usage.py`，`reserve`；`backend/app/core/clients.py:40`。
- 证据：代码确认。预算使用 `LLM_MAX_OUTPUT_TOKENS` 估算输出，构造 ChatOpenAI 时未传 max_tokens/max_completion_tokens 等对应参数。
- 影响：模型实际输出可显著超过预留；供应商超额只有结算后才能熔断，无法阻止已经发生的超支。
- 建议：将预算上限真正落实到调用参数，并按不同接口兼容性映射；超额结算作为兜底。

### 26. P2：未知费用过期后直接释放，账本会忘记已经发生的成本

- 位置：`backend/app/services/usage.py`，`settle`、`sweep_stale_reservations`、`get_usage`。
- 证据：代码确认。未知价格或缺少 usage 时只保留 usage_unknown；超时后改为 expired，没有生成费用事件；汇总也不再计入这部分占用或 unknown 标志。
- 影响：连续使用未知价格模型可在到期后重新获得预算，长期累计实际支出无法受原预算约束，界面还可能不再提示未知费用。
- 建议：将已发生但待对账费用与未调用成功的预留分开，不能按数据集 TTL 自动抹除；使用估算入账或人工对账流程。

## 图表、PPT 与异常处理

### 27. P2：AI 推荐的聚合方式被丢弃，图表可能与建议不一致

- 位置：`backend/app/api/endpoints/visualization.py`，`_validate_recommendation`；`backend/app/models/contracts.py`，`ChartRecommendation`；`frontend/src/pages/VisualizationPage.tsx`。
- 证据：代码确认。模型输出并校验 aggregation，但返回对象没有该字段，前端 create 继续用当前控件值或默认 sum。
- 影响：模型建议按均值比较时，最后可能画出求和图，尤其会改变合格率、时长和其他比率/均值指标的业务含义。
- 建议：聚合方式贯穿响应契约、控件和生成请求，并展示实际口径。

### 28. P2：图表输入校验不足，不存在的 X 轴会静默合并全部数据

- 位置：`backend/app/services/chart.py`，`generate`。
- 证据：已复现。X 轴填不存在列名、Y 值分别为 1 和 -1 时，得到一个空名称类别、数值 0 的成功结果。负值饼图也被直接放行。
- 影响：错误字段被伪装成正常统计，饼图占比口径没有得到基本保障。count 聚合仍预先要求每个 Y 值能转浮点，分类计数或含空值计数无法直接使用。
- 建议：校验列存在性、图表适用范围、计数定义和空值策略，必要时拒绝生成并给出业务提示。

### 29. P2：PPT 图表固定拉伸，多图时超出默认页面边界

- 位置：`backend/app/services/ppt.py:68`。
- 证据：几何尺寸已验证。默认 Presentation 宽 10 英寸，第二张图片右边界为 0.8+6.1+5.5=12.4 英寸，超出 2.4 英寸。
- 单图也同时强制宽 5.5、高 1.7 英寸，与前端图表原比例不同会被拉伸；API 允许最多 5 张图片，而没有分页布局。
- 建议：依据 slide_width/slide_height 自适应网格，保持图片比例；多图分页，长文本分页。当前前端只传一张图，多图越界主要影响 API 和后续扩展。

### 30. P2：PPT 定时清理可能删除正在写入的临时文件

- 位置：`backend/app/services/ppt.py:106`；`backend/app/services/maintenance.py`。
- 证据：条件风险。名为 purge_stale 的函数实际遍历并删除全部 `.*.tmp.pptx`，没有年龄判断、活动任务记录或锁；定时任务与生成可并行。
- 影响：生成正在保存时，临时文件可能被清理。是否直接删除成功受操作系统文件锁影响；失败窗口在支持删除打开文件的环境更明显。
- 建议：仅清理超过安全时间的孤儿文件，或登记活动生成任务并使用互斥保护。

### 31. P2：参数校验错误再次触发异常，422 变成 500

- 位置：`backend/app/core/errors.py:32`；`backend/app/models/contracts.py` 中 `CleaningRule.validate_target`。
- 证据：已复现。请求规则 `{"action":"median"}` 缺少 column，Pydantic 错误含 `ctx.error=ValueError(...)`；直接交给 JSONResponse 导致 `TypeError: Object of type ValueError is not JSON serializable`。
- 最小 FastAPI 验证实际返回 `500 / INTERNAL_ERROR`。
- 影响：正常输入错误被显示成服务器故障，日志产生额外堆栈，调用者无法准确修正参数。
- 建议：先编码/清洗 validation errors，去掉不可序列化的异常对象；参数错误使用通用请求错误码而非全部标成 CONFIG_INVALID。

## 测试、性能与维护

### 32. P2：端到端测试已经失效，且没有覆盖核心六步流程

- 位置：`frontend/e2e/smoke.spec.ts:9`；`frontend/src/pages/ConfigPage.tsx:33`；`frontend/src/test/wizardReducer.test.ts`。
- 证据：本次 Playwright 实际失败。测试寻找“模型与预算”，页面标题为“模型与协同”；后续部分表单标签也已改变。
- 当前只有一个配置页 E2E，前端单测只有 5 项，reducer 测试没有覆盖数据版本写入；因此 01 号阻断问题仍能通过 tsc、lint 和全部单测。
- 建议：维护与真实页面一致的稳定定位器；新增上传→确认→研讨→图表→下载，以及刷新恢复、修改上游失效、鉴权下载的回归测试。

### 33. P3：图表依赖包较大，关键业务代码挤在超长单行中

- 位置：`frontend/src/pages/VisualizationPage.tsx`、`frontend/src/context/WizardContext.tsx`、`frontend/src/pages/DataPage.tsx`。
- 证据：构建输出图表 chunk 约 1.15 MB，gzip 约 388.52 kB；代码多数业务处理挤在单行。
- 影响：首次打开图表有额外下载/解析成本；超长单行让 review、冲突解决和错误定位困难，状态依赖更难审查。
- 建议：按需引入 ECharts 图表/组件并复测包体；格式化代码，按加载、规则、持久化等职责拆分函数或 hook，不必先做大规模架构重写。

### 34. P3：README 对功能完成度的表述高于实际实现

- 位置：根目录 `README.md`；`frontend/src/pages/DataPage.tsx`、`PPTPage.tsx`。
- 证据：代码确认。README 描述类似 Excel 的在线编辑和手动微调，但数据表 render 仅输出字符串；“在线预览”实际是固定六页结构示意，不是生成 PPT 的渲染结果；技术栈还写 React 18，而 package.json 是 React 19。
- 影响：使用者按文档预期寻找不存在的操作；结构示意容易被误认为真实成果预览，无法发现排版问题。
- 建议：明确已实现/未实现功能，准确命名“结构预览”，同步依赖与运行条件，补真正需要的编辑或渲染能力。

## 推荐处理顺序

1. 先修 01、07、04、02、08、21，保证用户能走完流程且不会静默改错数据。
2. 修 17、22、23、24、25，再完善 18、26，收紧出站调用、凭据及费用边界。
3. 修 11 至 16、27 至 31，保证研讨有真实证据、可恢复、图表口径正确和成果可读。
4. 补 32 所列回归场景，再处理其他体验、性能及文档问题。

此次只新增本报告。已有未跟踪文件 `frontend/smoke.cjs`、`frontend/smoke-roles.png` 保持原样。构建及测试生成的本地产物不属于业务修复。
