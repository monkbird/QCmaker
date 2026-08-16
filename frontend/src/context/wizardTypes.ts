import type { EChartsOption } from 'echarts'
import type { DiscussionSummary, PPTResult } from '../types/api'
import type { DiscussionEvent } from '../types/discussion'
export interface WizardState { hydration:'loading'|'ready'|'failed';configStatus:'checking'|'ready'|'missing'|'degraded';currentProjectId:string;topic:string|null;dataRef:string|null;datasetRevision:number|null;dataConfirmed:boolean;discussionSessionId:string|null;lastEventSeq:number;discussionSummary:DiscussionSummary|null;chartOption:EChartsOption|null;chartImageRef:string|null;pptResult:PPTResult|null }
export type WizardAction =
  | {type:'HYDRATE_SUCCESS';payload:Partial<WizardState>}
  | {type:'HYDRATE_FAILED'}|{type:'SET_CONFIG_STATUS';payload:WizardState['configStatus']}
  | {type:'SET_TOPIC';payload:string}|{type:'SET_DATA_REF';payload:{dataRef:string;revision:number}}
  | {type:'CONFIRM_DATA'}|{type:'APPEND_DISCUSSION_EVENT';payload:DiscussionEvent}
  | {type:'SET_DISCUSSION_SESSION';payload:string}|{type:'SET_DISCUSSION_SUMMARY';payload:DiscussionSummary}
  | {type:'SET_CHART';payload:{option:EChartsOption;imageRef:string}}|{type:'SET_PPT_RESULT';payload:PPTResult}|{type:'RESET_PROJECT';payload:string}

