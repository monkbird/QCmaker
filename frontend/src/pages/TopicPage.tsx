import {
  ArrowRightOutlined,
  AuditOutlined,
  CheckOutlined,
  PaperClipOutlined,
  SendOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Empty,
  Input,
  Modal,
  Progress,
  Spin,
  Tag,
  Upload,
  message,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import {
  deleteDocument,
  ingestDocument,
  listDocuments,
  topicChat,
  topicHistory,
} from "../api/topic";
import { evaluateTopic } from "../api/insight";
import { errorMessage } from "../api/client";
import { StepPage } from "../components/StepPage";
import { useWizard } from "../context/WizardContext";
import type {
  ChatMessage,
  RagIngestResult,
  TopicEvaluation,
} from "../types/api";
import "./TopicPage.css";
import { MaterialWorkspace } from "../components/materials/MaterialWorkspace";
const DIMENSIONS: [
  keyof Pick<
    TopicEvaluation,
    "specific" | "measurable" | "achievable" | "relevant" | "time_bound"
  >,
  string,
][] = [
  ["specific", "具体性"],
  ["measurable", "可测量"],
  ["achievable", "可实现"],
  ["relevant", "相关性"],
  ["time_bound", "时限性"],
];
const ACCEPT = ".txt,.md,.markdown,.pdf,.docx,.xlsx,.xls,.csv,.pptx";
export function TopicPage() {
  const { state, setTopic } = useWizard();
  const [history, setHistory] = useState<ChatMessage[]>(
    state.topic ? [{ role: "assistant", content: state.topic }] : [],
  );
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [finalTopic, setFinalTopic] = useState(state.topic ?? "");
  const [evaluating, setEvaluating] = useState(false);
  const [evaluation, setEvaluation] = useState<TopicEvaluation | null>(null);
  const [evalOpen, setEvalOpen] = useState(false);
  const [materials, setMaterials] = useState<RagIngestResult[]>([]);
  const [uploading, setUploading] = useState(false);
  const [refCounts, setRefCounts] = useState<Record<number, number>>({});
  const navigate = useNavigate();
  const sending = useRef(false);
  const uploadQueue = useRef<Promise<void>>(Promise.resolve());
  const [materialsError, setMaterialsError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setHistory([]); setRefCounts({});
    void topicHistory(state.currentProjectId).then(items => {
      if (!cancelled) setHistory(items.flatMap(item => [{role:'user' as const,content:item.message},{role:'assistant' as const,content:item.response}]));
    }).catch(e => { if (!cancelled) setMaterialsError(errorMessage(e)); });
    void listDocuments(state.currentProjectId)
      .then((items) => {
        if (!cancelled) setMaterials(items);
      })
      .catch((e) => {
        if (!cancelled) setMaterialsError(errorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [state.currentProjectId]);
  const send = async (suggestion?: string) => {
    const text = (suggestion ?? input).trim();
    if (!text || sending.current) return;
    sending.current = true;
    const next = [...history, { role: "user" as const, content: text }];
    setHistory(next);
    setInput("");
    setBusy(true);
    try {
      const result = await topicChat(text, history, state.currentProjectId);
      setHistory([...next, { role: "assistant", content: result.response }]);
      if (result.references_used > 0)
        setRefCounts({ ...refCounts, [next.length]: result.references_used });
    } catch (e) {
      setHistory(history);
      setInput(text);
      message.error(errorMessage(e));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };
  const confirm = () => {
    const suggestion =
      [...history].reverse().find((item) => item.role === "assistant")
        ?.content ?? "";
    setFinalTopic(state.topic ?? suggestion.slice(0, 120));
    setOpen(true);
  };
  const evaluate = async () => {
    const candidate = (
      finalTopic ||
      state.topic ||
      input.trim() ||
      ([...history].reverse().find((item) => item.role === "assistant")
        ?.content ??
        "")
    ).trim();
    if (!candidate) {
      message.warning("请先描述或确认一个课题再评估");
      return;
    }
    setEvaluating(true);
    try {
      const result = await evaluateTopic(
        candidate.slice(0, 2000),
        state.currentProjectId,
      );
      setEvaluation(result);
      setEvalOpen(true);
    } catch (e) {
      message.error(errorMessage(e));
    } finally {
      setEvaluating(false);
    }
  };
  const upload = (file: File) => {
    setUploading(true);
    const queued = uploadQueue.current.then(async () => {
      try {
        const result = await ingestDocument(file, state.currentProjectId);
        setMaterials((prev) => [
          ...prev.filter((item) => item.document_id !== result.document_id),
          result,
        ]);
        setMaterialsError(null);
        message.success(`${result.filename} 已入库，切分 ${result.chunks} 段`);
      } catch (e) {
        message.error(errorMessage(e));
      }
    });
    uploadQueue.current = queued;
    void queued.finally(() => {
      if (uploadQueue.current === queued) setUploading(false);
    });
  };
  const removeMaterial = async (documentId: string) => {
    try {
      await deleteDocument(documentId, state.currentProjectId);
      setMaterials((current) =>
        current.filter((item) => item.document_id !== documentId),
      );
      message.success("资料已从当前项目知识库删除");
    } catch (e) {
      message.error(errorMessage(e));
    }
  };
  return (
    <StepPage
      eyebrow="01 · DEFINE"
      title="界定课题"
      description="还没想法也没关系。从日常工作聊起，一起找一个值得改善的小问题。"
      actions={
        <>
          <Button
            icon={<AuditOutlined />}
            loading={evaluating}
            onClick={() => void evaluate()}
          >
            SMART 辅助评估
          </Button>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            onClick={confirm}
          >
            确认课题
          </Button>
        </>
      }
    >
      <div className="topic-workbench">
        <section className="conversation">
          <div className="conversation-head">
            <span className="live-dot" />
            QC 课题顾问 <small>一次聊清一个问题</small>
          </div>
          <div className="messages">
            {history.length === 0 && (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="不用先准备数据或资料。说说你平时做什么，我们一起找方向。"
              />
            )}
            {history.map((item, index) => (
              <div key={index} className={`bubble bubble--${item.role}`}>
                <span>{item.role === "assistant" ? "顾问" : "我"}</span>
                <div className="bubble-body">
                  <p>{item.content}</p>
                  {!!refCounts[index] && (
                    <Tag className="ref-tag" color="blue">
                      参考了 {refCounts[index]} 条资料
                    </Tag>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="typing">
                <Spin size="small" /> 顾问正在思考
              </div>
            )}
          </div>
          <div style={{ padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <Button disabled={busy} onClick={() => void send('我还没有课题想法，也没有准备数据或资料，请带我从日常工作中一步步找方向，一次只问一个问题。')}>还没想法，帮我找方向</Button>
            <small>没有数据也能开始，之后再逐步补充。</small>
          </div>
          <div className="composer">
            <Input.TextArea
              disabled={busy}
              maxLength={4000}
              value={input}
              autoSize={{ minRows: 2, maxRows: 4 }}
              placeholder="随便聊聊你平时的工作，或直接说“还没想法”…"
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={() => void send()}
              loading={busy}
              aria-label="发送消息"
            />
          </div>
        </section>
        <aside className="method-strip">
          <MaterialWorkspace projectId={state.currentProjectId} compact />
          <details className="topic-extra-materials"><summary>其他资料上传与管理</summary><b>上传参考资料（可选）</b>
          <small>没有资料也可以先聊，确定方向后再补充。</small>
          <Upload.Dragger
            multiple
            accept={ACCEPT}
            showUploadList={false}
            disabled={uploading}
            beforeUpload={(file) => {
              void upload(file);
              return false;
            }}
            className="material-uploader"
          >
            <PaperClipOutlined />
            <p>{uploading ? "正在解析入库…" : "点击或拖入文档"}</p>
            <small>
              Word / Excel / PPT / PDF / Markdown / CSV / TXT，≤10MB
            </small>
          </Upload.Dragger>
          {materials.length > 0 && (
            <div className="material-tags">
              {materials.map((item) => (
                <Tag
                  key={item.document_id}
                  closable
                  onClose={(event) => {
                    event.preventDefault();
                    void removeMaterial(item.document_id);
                  }}
                >
                  {item.filename}·{item.chunks}段
                </Tag>
              ))}
            </div>
          )}
          {materialsError && (
            <Alert
              type="warning"
              message={`资料列表暂不可用：${materialsError}`}
            />
          )}
          <blockquote>
            资料仅用于当前项目；关闭标签将删除对应知识库内容。
          </blockquote>
          </details>
          <b>课题命名检查</b>
          <ol>
            <li>
              <span>01</span>对象是否明确
            </li>
            <li>
              <span>02</span>问题是否可测
            </li>
            <li>
              <span>03</span>目标是否可验证
            </li>
          </ol>
          <blockquote>对象 + 问题 + 改善方向</blockquote>
          {evaluation && (
            <Button type="link" onClick={() => setEvalOpen(true)}>
              查看上次评估结果
            </Button>
          )}
        </aside>
      </div>
      <Modal
        title="确认最终课题"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          if (!finalTopic.trim()) return;
          try {
            await setTopic(finalTopic.trim());
            setOpen(false);
            navigate("/authoring");
          } catch (e) {
            message.error(errorMessage(e));
          }
        }}
        okText="确认并开始编写"
        okButtonProps={{ icon: <ArrowRightOutlined /> }}
      >
        <Input.TextArea
          value={finalTopic}
          onChange={(e) => setFinalTopic(e.target.value)}
          rows={4}
          maxLength={120}
          showCount
        />
        <p className="modal-hint">
          修改已有课题将清空后续数据、研讨、图表与 PPT 成果。
        </p>
      </Modal>
      <Modal
        title={
          <span>
            <AuditOutlined /> SMART 课题评估
          </span>
        }
        open={evalOpen}
        onCancel={() => setEvalOpen(false)}
        footer={[
          <Button key="close" type="primary" onClick={() => setEvalOpen(false)}>
            知道了
          </Button>,
        ]}
      >
        {!evaluation ? (
          <div style={{ textAlign: "center", padding: 24 }}>
            <Spin />
          </div>
        ) : (
          <div>
            <p style={{ marginBottom: 12 }}>
              <b>结论：</b>
              {evaluation.verdict}{" "}
              {evaluation.references_used > 0 && (
                <Tag color="blue">
                  参考了 {evaluation.references_used} 条内部资料
                </Tag>
              )}
            </p>
            {DIMENSIONS.map(([key, label]) => (
              <div
                key={key}
                style={{
                  display: "grid",
                  gridTemplateColumns: "64px 1fr 40px",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                }}
              >
                <span>{label}</span>
                <Progress
                  percent={evaluation[key] * 20}
                  strokeColor={
                    evaluation[key] >= 4
                      ? "#52c41a"
                      : evaluation[key] >= 3
                        ? "#faad14"
                        : "#ff4d4f"
                  }
                  showInfo={false}
                />
                <b>{evaluation[key]}</b>
              </div>
            ))}
            <p style={{ marginTop: 12 }}>
              综合得分：<b style={{ fontSize: 18 }}>{evaluation.total}</b>/25
            </p>
            {evaluation.suggestions.length > 0 && (
              <div>
                <b>改进建议：</b>
                <ul style={{ paddingLeft: 20, margin: "6px 0" }}>
                  {evaluation.suggestions.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Modal>
    </StepPage>
  );
}
