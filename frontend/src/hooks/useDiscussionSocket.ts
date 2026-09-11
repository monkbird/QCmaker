import { useEffect, useRef, useState } from 'react';
import { loadDiscussionEvents } from '../storage/db';
import type { DiscussionCommand, DiscussionEvent } from '../types/discussion';
type Status = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'finished' | 'failed';
function wsUrl() {
    const explicit = import.meta.env.VITE_WS_BASE_URL;
    const token = import.meta.env.VITE_API_TOKEN ? `?token=${encodeURIComponent(String(import.meta.env.VITE_API_TOKEN))}` : '';
    if (explicit)
        return `${explicit.replace(/\/$/, '')}/discussion/ws${token}`;
    const url = new URL(import.meta.env.VITE_API_BASE_URL ?? '/api', location.origin);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${url.toString().replace(/\/$/, '')}/discussion/ws${token}`;
}
interface Options {
    topic: string;
    datasetId: string | null;
    revision: number | null;
    projectId: string;
    enabled: boolean;
    sessionId: string | null;
    lastEventSeq: number;
    onSession: (id: string) => void | Promise<void>;
    onEvent: (event: DiscussionEvent) => Promise<void>;
}
export function useDiscussionSocket(options: Options) {
    const [status, setStatus] = useState<Status>('idle');
    const [events, setEvents] = useState<DiscussionEvent[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [attempt, setAttempt] = useState(0);
    const [recoverable, setRecoverable] = useState(false);
    const socket = useRef<WebSocket | null>(null);
    const inputs = useRef(options);
    const activeSession = useRef(options.sessionId ?? crypto.randomUUID());
    const started = useRef(Boolean(options.sessionId));
    const lastSeq = useRef(0);
    const terminal = useRef(false);
    const needsRecovery = useRef(false);
    const recoveryRequested = useRef(false);
    const lastCommand = useRef<DiscussionCommand["type"] | null>(null);
    const processing = useRef<Promise<void>>(Promise.resolve());
    useEffect(() => { inputs.current = options; });
    useEffect(() => {
        if (!options.enabled)
            return;
        let disposed = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let ws: WebSocket | undefined;
        const connect = async () => {
            await processing.current;
            const current = inputs.current;
            if (current.sessionId) {
                activeSession.current = current.sessionId;
                started.current = true;
            }
            const saved = await loadDiscussionEvents(activeSession.current);
            if (disposed)
                return;
            setEvents(saved);
            lastSeq.current = saved.at(-1)?.event_seq ?? 0;
            const final = saved.find(event => event.type === 'finished');
            if (final) {
                terminal.current = true;
                setStatus('finished');
                return;
            }
            if (attempt > 5) {
                setStatus('failed');
                setError('自动重连次数已用尽，请重新连接');
                return;
            }
            terminal.current = false;
            setStatus(attempt ? 'reconnecting' : 'connecting');
            ws = new WebSocket(wsUrl());
            socket.current = ws;
            ws.onopen = async () => {
                if (disposed || !ws)
                    return;
                setStatus(needsRecovery.current ? 'failed' : 'connected');
                if (!needsRecovery.current)
                    setError(null);
                const command: DiscussionCommand = started.current
                    ? { type: 'resume', session_id: activeSession.current, client_message_id: crypto.randomUUID(), last_event_seq: lastSeq.current }
                    : { type: 'start', session_id: activeSession.current, client_message_id: crypto.randomUUID(), topic: current.topic, dataset_id: current.datasetId!, revision: current.revision!, project_id: current.projectId };
                try {
                    if (!started.current) {
                        await current.onSession(activeSession.current);
                        started.current = true;
                    }
                    if (!disposed && ws.readyState === WebSocket.OPEN) {
                        lastCommand.current = command.type;
                        ws.send(JSON.stringify(command));
                    }
                }
                catch {
                    setStatus('failed');
                    setError('会话保存失败，请重新连接');
                }
            };
            ws.onmessage = message => {
                processing.current = processing.current.then(async () => {
                    if (disposed)
                        return;
                    const parsed = JSON.parse(String(message.data)) as DiscussionEvent;
                    if (parsed.type === 'error' && parsed.event_seq === 0) {
                        if (parsed.error?.code === 'SESSION_NOT_FOUND' && lastCommand.current === 'resume' && ws?.readyState === WebSocket.OPEN) {
                            // The local session may have been saved before start reached the server.
                            const latest = inputs.current;
                            lastCommand.current = 'start';
                            ws.send(JSON.stringify({ type: 'start', session_id: activeSession.current, client_message_id: crypto.randomUUID(), topic: latest.topic, dataset_id: latest.datasetId!, revision: latest.revision!, project_id: latest.projectId } satisfies DiscussionCommand));
                            setStatus('connected');
                            setError(null);
                            return;
                        }
                        setError(parsed.error?.message ?? '研讨协议错误');
                        setStatus('failed');
                        return;
                    }
                    if (parsed.session_id !== activeSession.current || parsed.event_seq <= lastSeq.current)
                        return;
                    if (parsed.event_seq !== lastSeq.current + 1) {
                        ws?.close();
                        return;
                    }
                    await inputs.current.onEvent(parsed);
                    lastSeq.current = parsed.event_seq;
                    if (disposed)
                        return;
                    setEvents(previous => [...previous, parsed]);
                    if (parsed.type === 'finished' || parsed.session_status === 'finished') {
                        terminal.current = true;
                        setStatus('finished');
                        ws?.close();
                    }
                    else if (parsed.type === 'error' || parsed.session_status === 'round_error' || parsed.session_status === 'error') {
                        needsRecovery.current = parsed.recoverable === true || parsed.session_status === 'round_error';
                        setRecoverable(needsRecovery.current);
                        setError(parsed.error?.message ?? '上一轮研讨失败，请恢复当前轮次');
                        setStatus('failed');
                        if (needsRecovery.current && recoveryRequested.current && ws?.readyState === WebSocket.OPEN) {
                            recoveryRequested.current = false;
                            needsRecovery.current = false;
                            setRecoverable(false);
                            ws.send(JSON.stringify({ type: 'recover', session_id: activeSession.current, client_message_id: crypto.randomUUID() } satisfies DiscussionCommand));
                            setStatus('connected');
                            setError(null);
                        }
                    }
                    else if ((parsed.type === 'round_done' || parsed.session_status === 'round_done') && needsRecovery.current) {
                        needsRecovery.current = false;
                        recoveryRequested.current = false;
                        setRecoverable(false);
                        setError(null);
                        setStatus('connected');
                    }
                }).catch(() => { setError('研讨事件读取或保存失败，请重新连接'); setStatus('failed'); ws?.close(); });
            };
            ws.onerror = () => setError('研讨连接中断');
            ws.onclose = () => {
                if (disposed || terminal.current)
                    return;
                setStatus('reconnecting');
                timer = setTimeout(() => setAttempt(value => value + 1), Math.min(2 ** attempt * 1000, 10000));
            };
        };
        void connect().catch(() => { if (!disposed) {
            setStatus('failed');
            setError('无法恢复本地研讨记录，请重试');
        } });
        return () => { disposed = true; clearTimeout(timer); if (ws) {
            ws.onclose = null;
            ws.close();
        } };
    }, [options.enabled, attempt]);
    const transmit = (command: DiscussionCommand) => {
        if (socket.current?.readyState !== WebSocket.OPEN)
            return false;
        socket.current.send(JSON.stringify(command));
        return true;
    };
    const sendMessage = (content: string) => transmit({ type: 'message', session_id: activeSession.current, client_message_id: crypto.randomUUID(), content });
    const finish = () => {
        const sent = transmit({ type: 'finish', session_id: activeSession.current, client_message_id: crypto.randomUUID() });
        if (sent)
            setStatus('connecting');
        return sent;
    };
    const retry = () => {
        recoveryRequested.current = needsRecovery.current;
        if (needsRecovery.current && transmit({ type: 'recover', session_id: activeSession.current, client_message_id: crypto.randomUUID() })) {
            recoveryRequested.current = false;
            needsRecovery.current = false;
            setRecoverable(false);
            setError(null);
            setStatus('connected');
            return;
        }
        setAttempt(value => value >= 5 ? 0 : value + 1);
    };
    return { status, events, error, sendMessage, finish, retry, recoverable };
}
