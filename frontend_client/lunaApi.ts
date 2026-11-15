// Person 5 may replace these broad types with types generated from openapi.json.
export type Requirements = {
  dates_utc: string[];
  duration_hours: number;
  request?: string;
  mission_type?: string;
  objectives?: string[];
  priorities?: Record<string, number>;
  constraints?: Record<string, number>;
  require_navigation?: boolean;
  allow_mock_recommendation?: boolean;
};
export type PlanResponse = {
  mission_id: string;
  requirements: Requirements;
  candidates: unknown[];
  ranked_alternatives: unknown[];
  recommendation: unknown | null;
  warnings: string[];
  limitations: string[];
};
export class LunaApi {
  constructor(private baseUrl = 'http://127.0.0.1:8000') {}
  private async request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message ?? `HTTP ${response.status}`);
    return data as T;
  }
  health() { return this.request<{ status: string; mode: string }>('/health'); }
  plan(requirements: Requirements) { return this.request<PlanResponse>('/mission/plan', requirements); }
  replan(previous: PlanResponse, requirements: Requirements) {
    return this.request<PlanResponse>('/mission/replan', { previous, requirements });
  }
  compare(requirements: Requirements) {
    return this.request<{ baseline: PlanResponse; hybrid: PlanResponse; metrics: unknown }>('/mission/compare', { requirements });
  }
}
