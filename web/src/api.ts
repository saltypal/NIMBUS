export type Role = 'operator' | 'supervisor' | 'maintenance';
export type Actor = { person_id: string; display_name: string; role: Role };
export type Fields = Record<string, unknown>;
export type Machine = {
  _id: string;
  name: string;
  machine_type: string;
  organization?: string;
  production_stage?: string;
  parts?: string[];
  legacy_fixture?: boolean;
  legacy?: boolean;
  primary_product?: boolean;
};
export type ActionForm = { action: string; required: string[]; optional: string[]; roles: Role[] };
export type Policy = { source_id: string; policy_version: number; required_checks: Fields[] };
export type Forms = { actions: ActionForm[]; roles: Role[]; policies: Policy[]; statuses: string[] };
export type Ticket = {
  _id: string; machine_id: string; title: string; symptom: string; status: string;
  priority?: string | number; vehicle_id?: string; part_name?: string; production_stage?: string;
  version: number; repair_cycle: number; cycle_requires_new_work: boolean;
  reported_condition: string; next_action: { role: string; description: string } | null;
  verification_plan: {
    policy_id: string; policy_version: number; required_checks: Fields[];
    due?: string; verification_due_at?: string; shift?: string; verification_shift?: string;
  } | null;
  closure: Fields | null;
  activities: { event_id: string; action: string; actor: Actor; recorded_at: string; payload: Fields; status_after: string; submission_id: string }[];
};

export type DiagnosticWorker = {
  worker_id?: string; capability?: string; status?: string; model_id?: string;
  model_revision?: string; [key: string]: unknown;
};
export type Diagnostics = {
  database: {
    connected: boolean; backend: string; name: string; server_version?: string;
    collections?: Record<string, number>; mongodb_binary?: string | null; data_path?: string | null;
  };
  retrieval: { backend: string; vector_index_enabled: boolean; embedding_model?: string | null };
  workers: DiagnosticWorker[];
  jobs: { queued: number; leased: number; succeeded: number; failed: number };
  capabilities: Record<string, { configured: boolean; ready_workers: number }>;
};
export type InferenceTest = {
  _id: string; source_type: 'text' | 'audio' | 'handwriting'; capability: string;
  status: string; received_at: string; transcript: string | null; job_id?: string | null;
  error: string | null; worker_id?: string; model_id?: string; model_revision?: string;
  output_kind?: 'draft' | 'transcript'; draft?: Fields | null;
};
export type Advice = {
  enabled: boolean; status: string; suggestions: string[];
  citations: { source_id: string; chunk_id?: string }[]; context_sources: Fields[];
};
export type Vehicle = {
  _id: string; vehicle_id?: string; model?: string; current_stage?: string; production_stage?: string;
  status?: string; disposition?: string; line?: string; build?: string; inspection_summary?: Fields; [key: string]: unknown;
};
export type PartCheck = {
  _id: string; vehicle_id: string; machine_id: string; production_stage: string; part_name: string;
  result: 'pass' | 'issue' | 'pending'; note?: string; observed_at?: string; linked_ticket_id?: string | null;
};
export type Submission = {
  _id: string; actor: Actor; action: string; machine_id: string; ticket_id: string | null;
  processing_status: string; processing_version: number; selected_text_revision: number;
  draft_revision: number; source_type: string; purpose: string;
  text_revisions: { revision: number; origin: string; text: string }[];
  draft: { fields: Fields; summary: string; missing_fields: string[]; suggestions: string[]; citations: Fields[] } | null;
  draft_context?: { ticket: Ticket | null };
  error: { code: string; message?: string } | null;
  confirmation?: { status: string } | null;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const data = await response.json();
  if (!response.ok) {
    const error = data.error;
    const fields = error?.details?.fields?.join(', ');
    throw new Error(`${error?.message || data.detail || 'Request failed'}${fields ? ` Missing: ${fields}.` : ''}`);
  }
  return data as T;
}

export const jsonPost = <T,>(path: string, body: unknown) => api<T>(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export function label(value: string) {
  return value.replaceAll('_', ' ').replace(/^./, character => character.toUpperCase());
}
