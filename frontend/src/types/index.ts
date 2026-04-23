export interface FemaCategory {
  id: number;
  code: string;
  name: string;
  description: string;
}

export interface Claim {
  id: number;
  incident_name: string;
  county: string;
  applicant_name: string;
  fema_category_id: number | null;
  fema_code?: string;
  fema_category_name?: string;
  description: string;
  estimated_cost: number;
  approved_amount: number | null;
  status: string;
  ai_confidence_score: number | null;
  ai_flags: string | null;
  submitted_by: string;
  submitted_at: string;
  updated_at: string;
  document_count?: number;
  documents?: Document[];
  status_history?: StatusHistory[];
}

export interface Document {
  id: number;
  claim_id: number;
  file_name: string;
  file_type: string;
  file_size: number;
  storage_path: string | null;
  ai_extracted_vendor: string | null;
  ai_extracted_cost: number | null;
  ai_extracted_date: string | null;
  ai_extracted_category: string | null;
  ai_summary: string | null;
  ai_damage_description: string | null;
  processing_status: string;
  uploaded_at: string;
}

export interface StatusHistory {
  id: number;
  claim_id: number;
  old_status: string | null;
  new_status: string;
  changed_by: string;
  changed_at: string;
  notes: string | null;
}

export interface DashboardStats {
  total_claims: number;
  by_status: Record<string, number>;
  total_estimated_cost: number;
  total_approved_amount: number;
  by_category: { code: string; name: string; count: number; total_cost: number }[];
  by_county: { county: string; count: number; total_cost: number }[];
}

export const STATUS_COLORS: Record<string, string> = {
  submitted: '#2196f3',
  under_review: '#ff9800',
  ai_processed: '#9c27b0',
  approved: '#4caf50',
  rejected: '#f44336',
  needs_info: '#ff5722',
  packaged: '#00bcd4',
};

export const STATUS_LABELS: Record<string, string> = {
  submitted: 'Submitted',
  under_review: 'Under Review',
  ai_processed: 'Processed',
  approved: 'Approved',
  rejected: 'Rejected',
  needs_info: 'Needs Info',
  packaged: 'Packaged for FEMA',
};
