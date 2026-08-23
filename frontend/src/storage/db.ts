import { openDB, type DBSchema } from 'idb'
import type { EChartsOption } from 'echarts'
import type { ColumnInfo, DatasetResponse, DiscussionSummary, PPTResult } from '../types/api'
import type { DiscussionEvent } from '../types/discussion'

export interface StoredDataset { dataRef:string;projectId:string;dataset_id:string;revision:number;filename:string;sourceFile:Blob;columns:ColumnInfo[];rows:DatasetResponse['rows'];report:DatasetResponse['report'];updatedAt:number }
interface QCDb extends DBSchema {
  datasets:{key:string;value:StoredDataset;indexes:{'by-project':string}}
  discussion_events:{key:[string,number];value:DiscussionEvent}
  chart_images:{key:string;value:{chartImageRef:string;projectId:string;blob:Blob;mimeType:string;updatedAt:number};indexes:{'by-project':string}}
  project_state:{key:string;value:{projectId:string;discussionSummary:DiscussionSummary|null;chartOption:EChartsOption|null;pptResult:PPTResult|null;sessions:string[];updatedAt:number}}
}
const database = openDB<QCDb>('qcmaker',1,{upgrade(db){
  const datasets=db.createObjectStore('datasets',{keyPath:'dataRef'});datasets.createIndex('by-project','projectId')
  db.createObjectStore('discussion_events',{keyPath:['session_id','event_seq']})
  const images=db.createObjectStore('chart_images',{keyPath:'chartImageRef'});images.createIndex('by-project','projectId')
  db.createObjectStore('project_state',{keyPath:'projectId'})
}})
export const saveDataset = async (value:StoredDataset) => (await database).put('datasets',value)
export const loadDataset = async (ref:string) => (await database).get('datasets',ref)
export const saveDiscussionEvent = async (event:DiscussionEvent) => (await database).put('discussion_events',event)
export const loadDiscussionEvents = async (sessionId:string) => (await database).getAll('discussion_events',IDBKeyRange.bound([sessionId,0],[sessionId,Number.MAX_SAFE_INTEGER]))
export const saveChartImage = async (value:QCDb['chart_images']['value']) => (await database).put('chart_images',value)
export const loadChartImage = async (ref:string) => (await database).get('chart_images',ref)
export const loadProjectState = async (projectId:string) => (await database).get('project_state',projectId)
export const saveProjectState = async (value:QCDb['project_state']['value']) => (await database).put('project_state',value)
export async function clearProject(projectId:string){
  const db=await database
  const tx=db.transaction(['datasets','discussion_events','chart_images','project_state'],'readwrite')
  const state=await tx.objectStore('project_state').get(projectId)
  for(const sessionId of state?.sessions??[]){
    const range=IDBKeyRange.bound([sessionId,0],[sessionId,Number.MAX_SAFE_INTEGER])
    for(const key of await tx.objectStore('discussion_events').getAllKeys(range)) await tx.objectStore('discussion_events').delete(key)
  }
  for(const key of await tx.objectStore('datasets').index('by-project').getAllKeys(projectId)) await tx.objectStore('datasets').delete(key)
  for(const key of await tx.objectStore('chart_images').index('by-project').getAllKeys(projectId)) await tx.objectStore('chart_images').delete(key)
  await tx.objectStore('project_state').delete(projectId)
  await tx.done
}
