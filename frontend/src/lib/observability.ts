export interface ObservabilityRun {
  id: string;
  name: string;
  run_type: string;
  status: string;
  start_time: string | null;
  latency_ms: number | null;
  pipeline_latency_ms: number | null;
  visitor_id: string | null;
  error: string | null;
  url: string | null;
}

export interface RunsResponse {
  available: boolean;
  message: string | null;
  has_more: boolean;
  runs: ObservabilityRun[];
}

export interface RunStep {
  name: string;
  run_type: string;
  status: string;
  start_time: string | null;
  latency_ms: number | null;
  error: string | null;
  depth: number;
  inputs: unknown;
  outputs: unknown;
}

export interface RunDetail {
  id: string;
  name: string;
  status: string;
  start_time: string | null;
  latency_ms: number | null;
  pipeline_latency_ms: number | null;
  url: string | null;
  steps: RunStep[];
}

export interface RunDetailResponse {
  available: boolean;
  message: string | null;
  run: RunDetail | null;
}

export interface CostRollup {
  call_count: number;
  avg_latency_ms: number | null;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost_usd: number | null;
  recent: {
    id: number;
    created_at: string | null;
    latency_ms: number | null;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    cost_usd: number | null;
  }[];
}
