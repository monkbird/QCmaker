# 资料域验收记录

| 能力 | 当前状态 | 验证说明 |
|---|---|---|
| TXT/Markdown、CSV、XLSX/XLS、DOCX、PPTX、PDF文字 | 已实现离线解析 | `backend/tests/materials/test_document_coverage.py` |
| PDF扫描页识别 | 已接入本地适配 | 无文本页逐页渲染后调用OCR，失败仍保留页记录并标记待核验 |
| PNG/JPEG OCR | 已验证本地RapidOCR | `test_real_ocr.py`使用微软雅黑生成中文图像，识别文本与置信度通过；置信度不等于事实核验 |
| 原件持久化与版本 | 已验证 | 真实SQLite及浏览器上传、预览、确认、撤销通过 |
| 真实中文标准 | 已执行本地解析验收 | 20页中18页取得OCR内容，第2/8页保留失败记录 |
| 研究总结、QC样例语义核验 | 未执行专属验收 | 不以通用解析测试宣称所有业务材料正确 |

解析清单按页、幻灯片、工作表或文本块记录，空文本页不会被静默删除。`coverage_complete=false`时不得展示“全部读取正确”。

当前虚拟环境已验证PyMuPDF 1.28.2及RapidOCR 1.4.4；使用 Windows 微软雅黑字体以 Unicode 安全方式生成中文 PNG 与扫描 PDF，并通过真实 RapidOCR 断言识别文本，测试固化于 `backend/tests/materials/test_real_ocr.py`。可重复核验产物保存在 `.venv/acceptance/ocr/`。OCR与解析覆盖不能替代业务事实及图表语义核验。

本地标准文件《质量管理小组活动准则》标准.pdf已获授权复制至 `.venv/acceptance/standard/` 并在隔离 SQLite/资料存储中完成真实流式上传与解析：原件 `12,905,586` bytes，解析单元 `20` 页，完成 `18` 页，失败 `2` 页，覆盖完整性 `false`，状态 `needs_review`，总耗时 `113.61` 秒。第 `2`、`8` 页无可提取文本，真实 OCR/人工核验未形成可用内容，故保留为失败页并明确定位；该结果仅证明解析覆盖记录，不代表标准内容已事实核实。验收摘要保存在 `.venv/acceptance/standard/acceptance-summary.json`，原文不纳入 Git。
