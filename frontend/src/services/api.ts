import axios from 'axios';
import { Claim, DashboardStats, FemaCategory, Document } from '../types';
import { getApiErrorMessage } from '../utils/apiError';

/** Ensure requests hit `/api/...` on the backend (avoids POST → SPA catch-all → 405). */
function normalizeApiBase(): string {
  const raw = (process.env.REACT_APP_API_URL || 'http://localhost:8000').trim().replace(/\/$/, '');
  if (raw.endsWith('/api')) return raw;
  return `${raw}/api`;
}

const API_BASE = normalizeApiBase();

const api = axios.create({ baseURL: API_BASE });

export { getApiErrorMessage };

export async function fetchCurrentUser(): Promise<{ email: string; source: string }> {
  const { data } = await api.get('/current-user');
  return data;
}

export async function fetchCategories(): Promise<FemaCategory[]> {
  const { data } = await api.get('/categories');
  return data;
}

export async function fetchClaims(params?: { status?: string; county?: string }): Promise<Claim[]> {
  const { data } = await api.get('/claims', { params });
  return data;
}

export async function fetchClaim(id: number): Promise<Claim> {
  const { data } = await api.get(`/claims/${id}`);
  return data;
}

export async function createClaim(formData: FormData): Promise<Claim> {
  const { data } = await api.post('/claims', formData);
  return data;
}

/** AI damage text for new-claim form (image file or image URL, not both). */
export async function previewDamageDescription(
  file: File | null,
  url: string | null
): Promise<{ description: string; preview_storage_path?: string | null }> {
  const formData = new FormData();
  if (file) {
    formData.append('file', file);
  } else if (url) {
    formData.append('url', url);
  }
  // Path without leading slash so axios always resolves under baseURL (/api), not site root
  const { data } = await api.post('preview/damage-description', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function refineDescription(description: string): Promise<{ original: string; refined: string }> {
  const formData = new FormData();
  formData.append('description', description);
  const { data } = await api.post('/refine-description', formData);
  return data;
}

export async function updateClaimStatus(
  claimId: number,
  status: string,
  changedBy: string,
  notes: string,
  approvedAmount?: number
): Promise<Claim> {
  const formData = new FormData();
  formData.append('status', status);
  formData.append('changed_by', changedBy);
  formData.append('notes', notes);
  if (approvedAmount !== undefined) {
    formData.append('approved_amount', String(approvedAmount));
  }
  const { data } = await api.patch(`/claims/${claimId}/status`, formData);
  return data;
}

export async function uploadDocument(claimId: number, file: File): Promise<Document> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post(`/claims/${claimId}/documents`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function uploadDocumentFromUrl(claimId: number, url: string): Promise<Document> {
  const formData = new FormData();
  formData.append('url', url);
  const { data } = await api.post(`/claims/${claimId}/documents/url`, formData);
  return data;
}

export async function fetchDocuments(claimId: number): Promise<Document[]> {
  const { data } = await api.get(`/claims/${claimId}/documents`);
  return data;
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  const { data } = await api.get('/dashboard/stats');
  return data;
}
