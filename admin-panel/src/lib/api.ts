export type DashboardStats = {
  total_users: number; total_queries: number; queries_today: number;
  queries_week: number; queries_month: number; active_users: number;
  total_sessions: number; avg_response_time_ms: number;
  queries_by_day?: { date: string; count: number }[];
  rag_usage_percent?: number;
  recent_queries?: Query[]; recent_users?: User[];
};
export type Query = {
  id: string; user_id: string | null; user_email: string | null; user_name: string | null;
  query: string; assistant_response?: string; created_at: string; session_id: string;
  response_time_ms: number | null; model: string | null; rag_used: boolean | null; status?: string;
};
export type User = { user_id: string; user_name: string | null; user_email: string | null; total_queries: number; total_sessions: number; last_query: string | null; first_seen: string | null; avg_response_time_ms?: number | null };
export type Session = { id: string; user_id: string | null; user_name?: string | null; user_email?: string | null; created_at: string; updated_at: string; message_count?: number; query_count?: number; messages?: { id: string; role: string; content: string; model?: string | null; response_time_ms?: number | null; created_at: string }[] };
export type PageResult<T> = { items: T[]; page: number; page_size: number; total: number; pages: number };

export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/admin${path}`, { ...init, credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); message = body?.error?.message ?? body?.detail ?? message; } catch {}
    if (response.status === 404 || response.status === 405) message = "The admin API is not available yet. This frontend expects the protected /api/v1/admin endpoints described in the project README.";
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export function dateTime(value?: string | null) { return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—"; }
