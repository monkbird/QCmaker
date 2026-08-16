import type { WizardAction, WizardState } from './wizardTypes'
export const createInitialState = ():WizardState => ({hydration:'loading',configStatus:'checking',currentProjectId:crypto.randomUUID(),topic:null,dataRef:null,datasetRevision:null,dataConfirmed:false,discussionSessionId:null,lastEventSeq:0,discussionSummary:null,chartOption:null,chartImageRef:null,pptResult:null})
const clearAfterTopic = {dataRef:null,datasetRevision:null,dataConfirmed:false,discussionSessionId:null,lastEventSeq:0,discussionSummary:null,chartOption:null,chartImageRef:null,pptResult:null}
const clearAfterData = {dataConfirmed:false,discussionSessionId:null,lastEventSeq:0,discussionSummary:null,chartOption:null,chartImageRef:null,pptResult:null}
export function wizardReducer(state:WizardState,action:WizardAction):WizardState{switch(action.type){
  case'HYDRATE_SUCCESS':return{...state,...action.payload,hydration:'ready'}
  case'HYDRATE_FAILED':return{...state,hydration:'failed'}
  case'SET_CONFIG_STATUS':return{...state,configStatus:action.payload}
  case'SET_TOPIC':return action.payload===state.topic?state:{...state,...clearAfterTopic,topic:action.payload}
  case'SET_DATA_REF':return state.dataRef===action.payload.dataRef&&state.datasetRevision===action.payload.revision?state:{...state,...clearAfterData,...action.payload}
  case'CONFIRM_DATA':return{...state,dataConfirmed:true}
  case'SET_DISCUSSION_SESSION':return{...state,discussionSessionId:action.payload,lastEventSeq:0}
  case'APPEND_DISCUSSION_EVENT':return action.payload.event_seq<=state.lastEventSeq?state:{...state,lastEventSeq:action.payload.event_seq,discussionSessionId:action.payload.session_id,discussionSummary:action.payload.summary??state.discussionSummary}
  case'SET_DISCUSSION_SUMMARY':return{...state,discussionSummary:action.payload,chartOption:null,chartImageRef:null,pptResult:null}
  case'SET_CHART':return{...state,chartOption:action.payload.option,chartImageRef:action.payload.imageRef,pptResult:null}
  case'SET_PPT_RESULT':return{...state,pptResult:action.payload}
  case'RESET_PROJECT':return{...createInitialState(),hydration:'ready',configStatus:state.configStatus,currentProjectId:action.payload}
}}

