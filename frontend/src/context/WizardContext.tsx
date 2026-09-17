import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { EChartsOption } from 'echarts';
import { getConfig } from '../api/config';
import { errorMessage } from '../api/client';
import type { DatasetResponse, DiscussionSummary, PPTResult } from '../types/api';
import type { DiscussionEvent } from '../types/discussion';
import { saveChartImage, saveWizardSnapshot, type StoredDataset } from '../storage/db';
import { createInitialState, wizardReducer } from './wizardReducer';
import { restoreWizard } from './restoreWizard';
import type { WizardAction, WizardState } from './wizardTypes';
interface WizardValue {
    state: WizardState;
    notice: string | null;
    setConfigStatus: (status: WizardState['configStatus']) => void;
    setTopic: (topic: string) => Promise<void>;
    storeDataset: (dataset: DatasetResponse, file: File, dataRef?: string) => Promise<string>;
    confirmDataset: () => Promise<void>;
    appendEvent: (event: DiscussionEvent) => Promise<void>;
    setSession: (id: string) => Promise<void>;
    setSummary: (summary: DiscussionSummary) => Promise<void>;
    setChart: (option: EChartsOption, blob: Blob) => Promise<void>;
    setPpt: (result: PPTResult) => Promise<void>;
    reset: () => Promise<void>;
    openProject: (projectId: string) => Promise<void>;
}
const Context = createContext<WizardValue | null>(null);
const STORAGE_KEY = 'qcmaker_wizard';
export function WizardProvider({ children }: {
    children: ReactNode;
}) {
    const [state, setState] = useState(createInitialState);
    const [notice, setNotice] = useState<string | null>(null);
    const current = useRef(state);
    const pending = useRef<Promise<void>>(Promise.resolve());
    const initialization = useRef<Promise<void> | null>(null);
    const commit = useCallback((action: WizardAction, event?: DiscussionEvent, expected?: Pick<WizardState, 'currentProjectId' | 'topic' | 'dataRef' | 'datasetRevision'>, dataset?: StoredDataset): Promise<void> => {
        const job = pending.current.catch(() => undefined).then(async () => {
            if (expected && (current.current.currentProjectId !== expected.currentProjectId || current.current.topic !== expected.topic || current.current.dataRef !== expected.dataRef || current.current.datasetRevision !== expected.datasetRevision))
                throw new Error('项目或数据已变化，请重新操作');
            const next = wizardReducer(current.current, action);
            if (next === current.current)
                return;
            if (next.hydration === 'ready') {
                await saveWizardSnapshot(next, event, dataset);
                sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ currentProjectId: next.currentProjectId }));
            }
            // Publish only a durable state. A replay after a failed write must retry it.
            current.current = next;
            setState(next);
        });
        pending.current = job;
        void job.catch(() => setNotice('项目保存失败，请勿刷新；检查浏览器存储空间后重试'));
        return job;
    }, []);
    useEffect(() => {
        // StrictMode must not start two recovery uploads.
        if (initialization.current)
            return;
        initialization.current = (async () => {
            try {
                const raw: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '{}');
                const saved = raw && typeof raw === 'object' ? raw as Partial<WizardState> : {};
                const restored = await restoreWizard(saved);
                setNotice(restored.notice);
                await commit({ type: 'HYDRATE_SUCCESS', payload: restored.state });
            }
            catch (error) {
                setNotice(`恢复项目失败：${errorMessage(error)}`);
                await commit({ type: 'HYDRATE_FAILED' });
            }
            try {
                await commit({ type: 'SET_CONFIG_STATUS', payload: (await getConfig()).status });
            }
            catch {
                await commit({ type: 'SET_CONFIG_STATUS', payload: 'degraded' });
            }
        })();
    }, [commit]);
    const { currentProjectId, topic, dataRef: scopedDataRef, datasetRevision } = state;
    const actions = useMemo(() => {
        const expected = { currentProjectId, topic, dataRef: scopedDataRef, datasetRevision };
        return {
            setConfigStatus: (status: WizardState['configStatus']) => { void commit({ type: 'SET_CONFIG_STATUS', payload: status }).catch(() => undefined); },
            setTopic: (topic: string) => commit({ type: 'SET_TOPIC', payload: topic }, undefined, expected),
            storeDataset: async (dataset: DatasetResponse, file: File, existing?: string) => {
                const projectId = currentProjectId;
                if (current.current.currentProjectId !== projectId || current.current.topic !== topic)
                    throw new Error('项目已切换，请重新上传');
                const dataRef = existing ?? crypto.randomUUID();
                await commit({ type: 'SET_DATA_REF', payload: { dataRef, revision: dataset.revision } }, undefined, expected, { dataRef, projectId, ...dataset, sourceFile: file, updatedAt: Date.now() });
                return dataRef;
            },
            confirmDataset: () => commit({ type: 'CONFIRM_DATA' }, undefined, expected),
            appendEvent: (event: DiscussionEvent) => commit({ type: 'APPEND_DISCUSSION_EVENT', payload: event }, event, expected),
            setSession: (id: string) => commit({ type: 'SET_DISCUSSION_SESSION', payload: id }, undefined, expected),
            setSummary: (summary: DiscussionSummary) => commit({ type: 'SET_DISCUSSION_SUMMARY', payload: summary }, undefined, expected),
            setChart: async (option: EChartsOption, blob: Blob) => {
                const before = current.current;
                const imageRef = crypto.randomUUID();
                await saveChartImage({ chartImageRef: imageRef, projectId: before.currentProjectId, blob, mimeType: blob.type, updatedAt: Date.now() });
                if (current.current !== before)
                    throw new Error('项目状态已变化，请重新确认图表');
                await commit({ type: 'SET_CHART', payload: { option, imageRef } }, undefined, expected);
            },
            setPpt: (result: PPTResult) => commit({ type: 'SET_PPT_RESULT', payload: result }, undefined, expected),
            reset: async () => {
                await pending.current.catch(() => undefined);
                await commit({ type: 'RESET_PROJECT', payload: crypto.randomUUID() });
                setNotice(null);
            },
            openProject: async (projectId: string) => {
                await pending.current.catch(() => undefined);
                const restored = await restoreWizard({ currentProjectId: projectId });
                await commit({ type: 'HYDRATE_SUCCESS', payload: restored.state });
                setNotice(restored.notice);
            },
        };
    }, [commit, currentProjectId, topic, scopedDataRef, datasetRevision]);
    const value = useMemo<WizardValue>(() => ({ state, notice, ...actions }), [state, notice, actions]);
    return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useWizard() {
    const value = useContext(Context);
    if (!value)
        throw new Error('WizardProvider missing');
    return value;
}
