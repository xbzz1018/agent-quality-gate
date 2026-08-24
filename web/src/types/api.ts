export type TargetProtocol = 'http' | 'sse' | 'ag_ui' | 'a2a' | 'mcp'
export type TargetKind = 'agent' | 'tool'
export type RunStatus =
  | 'queued'
  | 'running'
  | 'cancel_requested'
  | 'cancelled'
  | 'completed'
  | 'failed'
export type VersionRole = 'baseline' | 'candidate'
export type GateDecision = 'ship' | 'warn' | 'block'
export type MeasurementStatus = 'known' | 'partial' | 'unknown'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Organization {
  id: number
  slug: string
  name: string
  active: boolean
  created_at?: string
}

export interface AuthUser {
  id: number
  username: string
  email: string | null
  display_name: string
  platform_admin: boolean
  organizations: Organization[]
  permissions: string[]
}

export interface LoginResult {
  access_token: string
  token_type: 'bearer'
  expires_at: string
  organizations: Organization[]
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Organization {
  id: number
  slug: string
  name: string
  active: boolean
  created_at?: string
}

export interface AuthUser {
  id: number
  username: string
  email: string | null
  display_name: string
  platform_admin: boolean
  organizations: Organization[]
  permissions: string[]
}

export interface LoginResult {
  access_token: string
  token_type: 'bearer'
  expires_at: string
  organizations: Organization[]
}

export interface Target {
  id: number
  organization_id: number
  name: string
  target_kind: TargetKind
  protocol: TargetProtocol
  endpoint: string
  auth_ref: string | null
  timeout_seconds: number
  capabilities: Record<string, unknown>
  enabled: boolean
  created_at: string
}

export interface AgentVersion {
  id: number
  target_id: number
  version: string
  model: string | null
  prompt_version: string | null
  tool_schema_hash: string | null
  metadata_json: Record<string, unknown>
  created_at: string
}

export interface DatasetCase {
  id: number
  external_id: string
  ordinal: number
  input_data: Record<string, unknown>
  expected: Record<string, unknown>
  tags: string[]
  sha256: string
}

export interface Dataset {
  id: number
  organization_id: number
  name: string
  version: string
  split: string
  sha256: string
  provenance: Record<string, unknown>
  frozen_at: string
  case_count: number
  cases?: DatasetCase[]
}

export interface EvalRun {
  id: number
  organization_id: number
  dataset_id: number
  baseline_version_id: number | null
  candidate_version_id: number
  replay_of_run_id: number | null
  status: RunStatus
  config: Record<string, unknown>
  manifest: Record<string, unknown>
  benchmark_mode: boolean
  expected_case_count: number
  completed_case_count: number
  failure_reason: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Usage {
  measurement_status: MeasurementStatus
  cost_status: MeasurementStatus
  input_tokens: number | null
  output_tokens: number | null
  cache_read_tokens: number | null
  cache_write_tokens: number | null
  reasoning_tokens: number | null
  embedding_tokens: number | null
  vision_tokens: number | null
  judge_tokens: number | null
  model_cost: string | null
  external_tool_cost: string | null
  cost_components: Record<string, unknown>
}

export interface ScoreRule {
  rule_id?: string
  id?: string
  category?: string
  expected?: unknown
  observed?: unknown
  score?: number
  passed?: boolean
  critical?: boolean
  failure_reason?: string | null
}

export interface CaseResult {
  id: number
  run_id: number
  case_id: number
  version_role: VersionRole
  attempt: number
  output: Record<string, unknown> | null
  final_action: string | null
  trace_id: string | null
  trace_url: string | null
  scores: { passed?: boolean; score?: number; rules?: ScoreRule[] }
  failure_type: string | null
  latency_ms: number | null
  usage: Usage | null
}

export interface RunEvent {
  id: number
  run_id: number
  case_result_id: number | null
  event_type: string
  source: string
  payload: Record<string, unknown>
  redacted: boolean
  occurred_at: string
}

export interface Metrics {
  case_count: number
  success_rate: number | null
  tool_argument_accuracy: number | null
  safety_violations: number
  p95_latency_ms: number | null
  average_model_cost: string | null
  external_tool_cost: string | null
}

export interface Comparison {
  status: 'ready'
  run_id: number
  baseline: Metrics
  candidate: Metrics
}

export interface BaselineRequired {
  status: 'baseline_required'
  run_id: number
  detail: string
  candidate: Metrics | null
}

export interface GateReason {
  rule_id: string
  severity: 'warn' | 'block'
  threshold: unknown
  actual: unknown
}

export interface GateResult {
  id: number
  run_id: number
  policy_id: number
  decision: GateDecision
  reasons: GateReason[]
  metric_deltas: Record<string, unknown>
  evaluated_at: string
}

export type ComparisonResponse = Comparison | BaselineRequired
export type GateResponse = GateResult | BaselineRequired

export interface GatePolicy {
  id: number
  organization_id: number
  name: string
  version: string
  thresholds: Record<string, number>
  active: boolean
  created_at: string
}

export interface PricingSnapshot {
  id: number
  organization_id: number
  provider: string
  model: string
  version: string
  currency: string
  effective_at: string
  prices: Record<string, string>
  source: string
  created_at: string
}

export interface DemoBootstrapResult {
  demo_fixture: true
  target_id: number
  baseline_version_id: number
  candidate_version_id: number
  dataset_id: number
  gate_policy_id: number
  pricing_snapshot_id: number
  created_resources: string[]
}

export interface DashboardSummary {
  target_count: number
  active_target_count: number
  run_count: number
  completed_run_count: number
  failed_run_count: number
  latest_gate_decisions: Array<{ run_id: number; decision: GateDecision; evaluated_at: string }>
  failure_categories: Array<{ failure_type: string; count: number }>
  run_trend: Array<Record<string, number | string>>
}

export interface UsageSummary {
  input_tokens: number | null
  output_tokens: number | null
  cache_read_tokens: number | null
  cache_write_tokens: number | null
  reasoning_tokens: number | null
  embedding_tokens: number | null
  vision_tokens: number | null
  judge_tokens: number | null
  model_cost: string | null
  external_tool_cost: string | null
  unknown_measurement_ratio: number
  unknown_cost_ratio: number
  groups: Array<{
    key: string
    input_tokens: number | null
    output_tokens: number | null
    model_cost: string | null
    external_tool_cost: string | null
    unknown_ratio: number
  }>
}

export interface Role {
  id: number
  organization_id: number
  name: string
  description: string
  system: boolean
  permission_codes: string[]
}

export interface Permission {
  id: number
  code: string
  name: string
  description: string
}

export interface Member {
  membership_id: number
  user_id: number
  username: string
  display_name: string
  email: string | null
  active: boolean
  role_ids: number[]
  role_names: string[]
}

export interface ServiceAccount {
  id: number
  organization_id: number
  name: string
  description: string
  active: boolean
  created_at: string
}

export interface ApiKeyRecord {
  id: number
  service_account_id: number
  name: string
  prefix: string
  api_key?: string
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export interface AuditLog {
  id: number
  organization_id: number | null
  actor_type: string
  actor_id: number | null
  action: string
  resource_type: string | null
  resource_id: string | null
  outcome: string
  details: Record<string, unknown>
  created_at: string
}

export interface SystemSetting {
  id: number
  organization_id: number | null
  key: string
  value: Record<string, unknown>
  updated_at: string
}

export interface DashboardSummary {
  target_count: number
  active_target_count: number
  run_count: number
  completed_run_count: number
  failed_run_count: number
  latest_gate_decisions: Array<{ run_id: number; decision: GateDecision; evaluated_at: string }>
  failure_categories: Array<{ failure_type: string; count: number }>
  run_trend: Array<Record<string, number | string>>
}

export interface UsageSummary {
  input_tokens: number | null
  output_tokens: number | null
  cache_read_tokens: number | null
  cache_write_tokens: number | null
  reasoning_tokens: number | null
  embedding_tokens: number | null
  vision_tokens: number | null
  judge_tokens: number | null
  model_cost: string | null
  external_tool_cost: string | null
  unknown_measurement_ratio: number
  unknown_cost_ratio: number
  groups: Array<{
    key: string
    input_tokens: number | null
    output_tokens: number | null
    model_cost: string | null
    external_tool_cost: string | null
    unknown_ratio: number
  }>
}

export interface Role {
  id: number
  organization_id: number
  name: string
  description: string
  system: boolean
  permission_codes: string[]
}

export interface Permission {
  id: number
  code: string
  name: string
  description: string
}

export interface Member {
  membership_id: number
  user_id: number
  username: string
  display_name: string
  email: string | null
  active: boolean
  role_ids: number[]
  role_names: string[]
}

export interface ServiceAccount {
  id: number
  organization_id: number
  name: string
  description: string
  active: boolean
  created_at: string
}

export interface ApiKeyRecord {
  id: number
  service_account_id: number
  name: string
  prefix: string
  api_key?: string
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export interface AuditLog {
  id: number
  organization_id: number | null
  actor_type: string
  actor_id: number | null
  action: string
  resource_type: string | null
  resource_id: string | null
  outcome: string
  details: Record<string, unknown>
  created_at: string
}

export interface SystemSetting {
  id: number
  organization_id: number | null
  key: string
  value: Record<string, unknown>
  updated_at: string
}
