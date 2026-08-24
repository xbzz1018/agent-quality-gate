import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'

import type {
  AgentVersion,
  ApiKeyRecord,
  AuditLog,
  AuthUser,
  CaseResult,
  ComparisonResponse,
  DashboardSummary,
  Dataset,
  DemoBootstrapResult,
  EvalRun,
  GatePolicy,
  GateResult,
  GateResponse,
  LoginResult,
  Member,
  Organization,
  Page,
  Permission,
  PricingSnapshot,
  PolicyBundle,
  PolicyEvaluation,
  Role,
  RunEvent,
  ServiceAccount,
  SkillPackage,
  SkillScan,
  SkillVersion,
  SystemSetting,
  Target,
  UsageSummary,
} from '@/types/api'

export const http = axios.create({ baseURL: '/api/v1', timeout: 20_000, withCredentials: true })

let accessToken: string | null = null
let organizationId: number | null = null
let refreshPromise: Promise<string> | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function setOrganization(id: number | null) {
  organizationId = id
}

http.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  if (organizationId) config.headers['X-Organization-ID'] = String(organizationId)
  return config
})

http.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
  const path = config?.url ?? ''
  if (
    error.response?.status !== 401 ||
    !config ||
    config._retried ||
    path.includes('/auth/login') ||
    path.includes('/auth/refresh')
  ) {
    return Promise.reject(error)
  }
  config._retried = true
  try {
    refreshPromise ??= axios
      .post<LoginResult>('/api/v1/auth/refresh', {}, { withCredentials: true })
      .then(({ data }) => {
        setAccessToken(data.access_token)
        return data.access_token
      })
      .finally(() => {
        refreshPromise = null
      })
    config.headers.Authorization = `Bearer ${await refreshPromise}`
    return http(config)
  } catch (refreshError) {
    setAccessToken(null)
    window.dispatchEvent(new CustomEvent('aqh:auth-expired'))
    return Promise.reject(refreshError)
  }
})

export const api = {
  login: (username: string, password: string) =>
    http.post<LoginResult>('/auth/login', { username, password }).then(({ data }) => data),
  refresh: () => http.post<LoginResult>('/auth/refresh').then(({ data }) => data),
  logout: () => http.post('/auth/logout'),
  me: () => http.get<AuthUser>('/auth/me').then(({ data }) => data),
  sessions: () => http.get('/auth/sessions').then(({ data }) => data),
  revokeSession: (id: number) => http.delete(`/auth/sessions/${id}`),
  adminSessions: () => http.get('/admin/sessions').then(({ data }) => data),
  revokeAdminSession: (id: number) => http.delete(`/admin/sessions/${id}`),
  organizations: () => http.get<Organization[]>('/organizations').then(({ data }) => data),
  createOrganization: (payload: Record<string, unknown>) =>
    http.post<Organization>('/organizations', payload).then(({ data }) => data),
  targets: (params: Record<string, unknown> = {}) =>
    http.get<Page<Target>>('/targets', { params }).then(({ data }) => data),
  createTarget: (payload: Record<string, unknown>) =>
    http.post<Target>('/targets', payload).then(({ data }) => data),
  versions: (targetId: number) =>
    http.get<AgentVersion[]>(`/targets/${targetId}/versions`).then(({ data }) => data),
  createVersion: (targetId: number, payload: Record<string, unknown>) =>
    http.post<AgentVersion>(`/targets/${targetId}/versions`, payload).then(({ data }) => data),
  datasets: (params: Record<string, unknown> = {}) =>
    http.get<Page<Dataset>>('/datasets', { params }).then(({ data }) => data),
  dataset: (id: number) => http.get<Dataset>(`/datasets/${id}`).then(({ data }) => data),
  importDataset: (payload: Record<string, unknown>) =>
    http.post<Dataset>('/datasets/import', payload).then(({ data }) => data),
  runs: (params: Record<string, unknown> = {}) =>
    http.get<Page<EvalRun>>('/eval-runs', { params }).then(({ data }) => data),
  run: (id: number) => http.get<EvalRun>(`/eval-runs/${id}`).then(({ data }) => data),
  createRun: (payload: Record<string, unknown>) =>
    http.post<EvalRun>('/eval-runs', payload).then(({ data }) => data),
  results: (runId: number) =>
    http.get<CaseResult[]>(`/eval-runs/${runId}/results`).then(({ data }) => data),
  searchResults: (params: Record<string, unknown> = {}) =>
    http.get<Page<CaseResult>>('/results/search', { params }).then(({ data }) => data),
  events: (runId: number) =>
    http.get<RunEvent[]>(`/eval-runs/${runId}/events`).then(({ data }) => data),
  cancelRun: (runId: number) =>
    http.post<EvalRun>(`/eval-runs/${runId}/cancel`).then(({ data }) => data),
  replayRun: (runId: number, caseIds?: string[]) =>
    http.post<EvalRun>(`/eval-runs/${runId}/replay`, { case_ids: caseIds }).then(({ data }) => data),
  comparison: (runId: number) =>
    http.get<ComparisonResponse>(`/eval-runs/${runId}/comparison`).then(({ data }) => data),
  gate: (runId: number) =>
    http.get<GateResponse>(`/eval-runs/${runId}/gate`).then(({ data }) => data),
  gateAudits: (params: Record<string, unknown> = {}) =>
    http.get<Page<GateResult>>('/gate-audits', { params }).then(({ data }) => data),
  policies: () => http.get<GatePolicy[]>('/gate-policies').then(({ data }) => data),
  createGatePolicy: (payload: Record<string, unknown>) =>
    http.post<GatePolicy>('/gate-policies', payload).then(({ data }) => data),
  skills: (params: Record<string, unknown> = {}) =>
    http.get<Page<SkillPackage>>('/skills', { params }).then(({ data }) => data),
  skillVersions: (skillId: number) =>
    http.get<SkillVersion[]>(`/skills/${skillId}/versions`).then(({ data }) => data),
  importSkill: (payload: Record<string, unknown>) =>
    http.post('/skills/import', payload).then(({ data }) => data),
  skillScans: (versionId: number) =>
    http.get<SkillScan[]>(`/skill-versions/${versionId}/scans`).then(({ data }) => data),
  scanSkill: (versionId: number) =>
    http.post<SkillScan>(`/skill-versions/${versionId}/scan`).then(({ data }) => data),
  attachSkill: (versionId: number, skillVersionId: number) =>
    http.put(`/versions/${versionId}/skills/${skillVersionId}`).then(({ data }) => data),
  skillRegression: (runId: number) =>
    http.get(`/eval-runs/${runId}/skill-regression`).then(({ data }) => data),
  policyBundles: (params: Record<string, unknown> = {}) =>
    http.get<Page<PolicyBundle>>('/policy-bundles', { params }).then(({ data }) => data),
  createPolicyBundle: (payload: Record<string, unknown>) =>
    http.post<PolicyBundle>('/policy-bundles', payload).then(({ data }) => data),
  policyEvaluation: (runId: number) =>
    http
      .get<PolicyEvaluation>(`/eval-runs/${runId}/policy-evaluation`)
      .then(({ data }) => data),
  pricing: () => http.get<PricingSnapshot[]>('/pricing-snapshots').then(({ data }) => data),
  dashboard: () => http.get<DashboardSummary>('/dashboard/summary').then(({ data }) => data),
  usage: (params: Record<string, unknown> = {}) =>
    http.get<UsageSummary>('/usage/summary', { params }).then(({ data }) => data),
  bootstrapDemo: () =>
    http.post<DemoBootstrapResult>('/demo/bootstrap', {}).then(({ data }) => data),
  members: () => http.get<Member[]>('/members').then(({ data }) => data),
  createMember: (payload: Record<string, unknown>) =>
    http.post<Member>('/members', payload).then(({ data }) => data),
  updateMember: (id: number, payload: Record<string, unknown>) =>
    http.patch<Member>(`/members/${id}`, payload).then(({ data }) => data),
  roles: () => http.get<Role[]>('/roles').then(({ data }) => data),
  permissions: () => http.get<Permission[]>('/permissions').then(({ data }) => data),
  createRole: (payload: Record<string, unknown>) =>
    http.post<Role>('/roles', payload).then(({ data }) => data),
  updateRole: (id: number, payload: Record<string, unknown>) =>
    http.patch<Role>(`/roles/${id}`, payload).then(({ data }) => data),
  serviceAccounts: () =>
    http.get<ServiceAccount[]>('/service-accounts').then(({ data }) => data),
  createServiceAccount: (payload: Record<string, unknown>) =>
    http.post<ServiceAccount>('/service-accounts', payload).then(({ data }) => data),
  apiKeys: (accountId: number) =>
    http.get<ApiKeyRecord[]>(`/service-accounts/${accountId}/api-keys`).then(({ data }) => data),
  createApiKey: (accountId: number, payload: Record<string, unknown>) =>
    http
      .post<ApiKeyRecord>(`/service-accounts/${accountId}/api-keys`, payload)
      .then(({ data }) => data),
  revokeApiKey: (id: number) => http.delete(`/api-keys/${id}`),
  auditLogs: (params: Record<string, unknown> = {}) =>
    http.get<AuditLog[]>('/audit-logs', { params }).then(({ data }) => data),
  settings: () => http.get<SystemSetting[]>('/settings').then(({ data }) => data),
  putSetting: (key: string, value: Record<string, unknown>) =>
    http.put<SystemSetting>(`/settings/${key}`, { value }).then(({ data }) => data),
  platformSettings: () =>
    http.get<SystemSetting[]>('/platform/settings').then(({ data }) => data),
  putPlatformSetting: (key: string, value: Record<string, unknown>) =>
    http.put<SystemSetting>(`/platform/settings/${key}`, { value }).then(({ data }) => data),
}

export function apiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail) return JSON.stringify(detail)
    return error.message
  }
  return error instanceof Error ? error.message : '请求失败'
}
