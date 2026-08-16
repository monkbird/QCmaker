import type { AppError, DiscussionSummary } from './api'
export type AgentRole = 'moderator'|'researcher'|'analyst'|'critic'|'writer'
export interface DiscussionCommand { type:'start'|'message'|'resume'|'finish';session_id:string;client_message_id:string;last_event_seq?:number;topic?:string;data_summary?:string;content?:string }
export interface DiscussionEvent { type:'ack'|'agent_message'|'round_done'|'finished'|'error';session_id:string;event_seq:number;timestamp:string;reply_to_client_message_id?:string;agent?:AgentRole;content?:string;summary?:DiscussionSummary;round?:number;recoverable?:boolean;error?:AppError }

