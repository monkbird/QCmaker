import { llmApi } from './client'
import type { CleaningAdviceResponse, ChartInsightResponse, TopicEvaluation } from '../types/api'
export const evaluateTopic = async (topic:string) => (await llmApi.post<TopicEvaluation>('/topic/evaluate', {topic})).data
export const adviseCleaning = async (datasetId:string) => (await llmApi.post<CleaningAdviceResponse>('/data/advise', {dataset_id: datasetId})).data
export const chartInsight = async (datasetId:string, revision:number, focus='') => (await llmApi.post<ChartInsightResponse>('/visualization/insight', {dataset_id: datasetId, revision, focus})).data
