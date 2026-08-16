import { api } from './client'
import type { ChartRecommendation, ChartRequest, ChartResponse, ColumnInfo, DataRow } from '../types/api'
export const generateChart = async (input:ChartRequest) => (await api.post<ChartResponse>('/visualization/generate',input)).data
export const recommendChart = async (columns:ColumnInfo[],sample_rows:DataRow[]) => (await api.post<ChartRecommendation>('/visualization/recommend',{columns,sample_rows})).data

