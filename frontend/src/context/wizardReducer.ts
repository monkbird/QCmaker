import type { WizardAction, WizardState } from './wizardTypes';
export const createInitialState = (): WizardState => ({ datasetRefs: [], materialRefs: [], chapterRefs: [], artifactRefs: [], legacyArtifactsStale: false, hydration: 'loading', configStatus: 'checking', currentProjectId: crypto.randomUUID(), topic: null, dataRef: null, datasetRevision: null, dataConfirmed: false, discussionSessionId: null, lastEventSeq: 0, discussionSummary: null, chartOption: null, chartImageRef: null, pptResult: null });
const clearAfterData = { dataConfirmed: false, discussionSessionId: null, lastEventSeq: 0, discussionSummary: null, chartOption: null, chartImageRef: null, pptResult: null };
export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
    switch (action.type) {
        case 'HYDRATE_SUCCESS': return { ...state, ...action.payload, datasetRefs: [...new Set([...(action.payload.datasetRefs ?? []), ...(action.payload.dataRef ? [action.payload.dataRef] : [])])], hydration: 'ready' };
        case 'HYDRATE_FAILED': return { ...state, hydration: 'failed' };
        case 'SET_CONFIG_STATUS': return { ...state, configStatus: action.payload };
        case 'SET_TOPIC': return action.payload === state.topic ? state : { ...state, topic: action.payload, legacyArtifactsStale: Boolean(state.topic) };
        case 'SET_DATA_REF': return state.dataRef === action.payload.dataRef && state.datasetRevision === action.payload.revision ? state : { ...state, ...clearAfterData, dataRef: action.payload.dataRef, datasetRevision: action.payload.revision, datasetRefs: [...new Set([...state.datasetRefs, ...(state.dataRef ? [state.dataRef] : []), action.payload.dataRef])] };
        case 'CONFIRM_DATA': return { ...state, dataConfirmed: true };
        case 'SET_DISCUSSION_SESSION': return state.discussionSessionId === action.payload ? state : { ...state, discussionSessionId: action.payload, lastEventSeq: 0, discussionSummary: null, chartOption: null, chartImageRef: null, pptResult: null };
        case 'APPEND_DISCUSSION_EVENT': return action.payload.session_id !== state.discussionSessionId || action.payload.event_seq <= state.lastEventSeq ? state : { ...state, lastEventSeq: action.payload.event_seq, ...(action.payload.summary ? { discussionSummary: action.payload.summary, chartOption: null, chartImageRef: null, pptResult: null } : {}) };
        case 'SET_DISCUSSION_SUMMARY': return { ...state, discussionSummary: action.payload, chartOption: null, chartImageRef: null, pptResult: null };
        case 'SET_CHART': return { ...state, chartOption: action.payload.option, chartImageRef: action.payload.imageRef, pptResult: null };
        case 'SET_PPT_RESULT': return { ...state, pptResult: action.payload };
        case 'RESET_PROJECT': return { ...createInitialState(), hydration: 'ready', configStatus: state.configStatus, currentProjectId: action.payload };
    }
}
