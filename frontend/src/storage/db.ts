import { openDB, type DBSchema } from 'idb';
import type { EChartsOption } from 'echarts';
import type { ColumnInfo, DatasetResponse, DiscussionSummary, PPTResult } from '../types/api';
import type { DiscussionEvent } from '../types/discussion';
import type { WizardState } from '../context/wizardTypes';
export interface StoredDataset {
    dataRef: string;
    projectId: string;
    dataset_id: string;
    revision: number;
    filename: string;
    sourceFile: Blob;
    columns: ColumnInfo[];
    rows: DatasetResponse['rows'];
    report: DatasetResponse['report'];
    updatedAt: number;
}
interface QCDb extends DBSchema {
    datasets: {
        key: string;
        value: StoredDataset;
        indexes: {
            'by-project': string;
        };
    };
    discussion_events: {
        key: [
            string,
            number
        ];
        value: DiscussionEvent;
    };
    chart_images: {
        key: string;
        value: {
            chartImageRef: string;
            projectId: string;
            blob: Blob;
            mimeType: string;
            updatedAt: number;
        };
        indexes: {
            'by-project': string;
        };
    };
    project_state: {
        key: string;
        value: {
            projectId: string;
            discussionSummary: DiscussionSummary | null;
            chartOption: EChartsOption | null;
            pptResult: PPTResult | null;
            sessions: string[];
            updatedAt: number;
            snapshot?: WizardState;
        };
    };
}
const database = openDB<QCDb>('qcmaker', 2, { upgrade(db, oldVersion, _newVersion, tx) {
    if (oldVersion < 1) {
        const datasets = db.createObjectStore('datasets', { keyPath: 'dataRef' });
        datasets.createIndex('by-project', 'projectId');
        db.createObjectStore('discussion_events', { keyPath: ['session_id', 'event_seq'] });
        const images = db.createObjectStore('chart_images', { keyPath: 'chartImageRef' });
        images.createIndex('by-project', 'projectId');
        db.createObjectStore('project_state', { keyPath: 'projectId' });
    }
    if (oldVersion >= 1 && oldVersion < 2) {
        void (async () => {
            let cursor = await tx.objectStore('project_state').openCursor();
            while (cursor) {
                const value = cursor.value;
                if (value.snapshot) {
                    const snapshot = value.snapshot;
                    await cursor.update({ ...value, snapshot: { ...snapshot,
                        datasetRefs: [...new Set([...(snapshot.datasetRefs ?? []), ...(snapshot.dataRef ? [snapshot.dataRef] : [])])],
                        materialRefs: snapshot.materialRefs ?? [], chapterRefs: snapshot.chapterRefs ?? [], artifactRefs: snapshot.artifactRefs ?? [],
                        legacyArtifactsStale: snapshot.legacyArtifactsStale ?? false,
                    }});
                }
                cursor = await cursor.continue();
            }
        })();
    }
    } });
export const listSavedProjects = async () => (await database).getAll('project_state');
export const listProjectDatasets = async (projectId: string) => (await database).getAllFromIndex('datasets', 'by-project', projectId);
export const saveDataset = async (value: StoredDataset) => (await database).put('datasets', value);
export const loadDataset = async (ref: string) => (await database).get('datasets', ref);
export const saveDiscussionEvent = async (event: DiscussionEvent) => (await database).put('discussion_events', event);
export const loadDiscussionEvents = async (sessionId: string) => (await database).getAll('discussion_events', IDBKeyRange.bound([sessionId, 0], [sessionId, Number.MAX_SAFE_INTEGER]));
export const saveChartImage = async (value: QCDb['chart_images']['value']) => (await database).put('chart_images', value);
export const loadChartImage = async (ref: string) => (await database).get('chart_images', ref);
export const loadProjectState = async (projectId: string) => (await database).get('project_state', projectId);
export const saveProjectState = async (value: QCDb['project_state']['value']) => (await database).put('project_state', value);
// Event and acknowledged sequence share one transaction.
export async function saveWizardSnapshot(snapshot: WizardState, event?: DiscussionEvent, dataset?: StoredDataset) {
    const db = await database;
    const tx = db.transaction(['project_state', 'discussion_events', 'datasets'], 'readwrite');
    const previous = await tx.objectStore('project_state').get(snapshot.currentProjectId);
    const sessions = new Set(previous?.sessions ?? []);
    if (snapshot.discussionSessionId)
        sessions.add(snapshot.discussionSessionId);
    if (event)
        await tx.objectStore('discussion_events').put(event);
    if (dataset)
        await tx.objectStore('datasets').put(dataset);
    await tx.objectStore('project_state').put({ projectId: snapshot.currentProjectId, snapshot, discussionSummary: snapshot.discussionSummary, chartOption: snapshot.chartOption, pptResult: snapshot.pptResult, sessions: [...sessions], updatedAt: Date.now() });
    await tx.done;
}
export async function clearProject(projectId: string) {
    const db = await database;
    const tx = db.transaction(['datasets', 'discussion_events', 'chart_images', 'project_state'], 'readwrite');
    const state = await tx.objectStore('project_state').get(projectId);
    for (const sessionId of state?.sessions ?? []) {
        const range = IDBKeyRange.bound([sessionId, 0], [sessionId, Number.MAX_SAFE_INTEGER]);
        for (const key of await tx.objectStore('discussion_events').getAllKeys(range))
            await tx.objectStore('discussion_events').delete(key);
    }
    for (const key of await tx.objectStore('datasets').index('by-project').getAllKeys(projectId))
        await tx.objectStore('datasets').delete(key);
    for (const key of await tx.objectStore('chart_images').index('by-project').getAllKeys(projectId))
        await tx.objectStore('chart_images').delete(key);
    await tx.objectStore('project_state').delete(projectId);
    await tx.done;
}
