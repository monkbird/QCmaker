import { api } from './client';
import type { PPTRequest, PPTResult } from '../types/api';
export const generatePpt = async (input: PPTRequest) => (await api.post<PPTResult>('/ppt/generate', input)).data;
export async function downloadPpt(fileId: string, filename: string) {
    const response = await api.get<Blob>(`/ppt/download/${encodeURIComponent(fileId)}`, { responseType: 'blob' });
    const url = URL.createObjectURL(response.data);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    // Let the browser begin reading before releasing the object URL.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
