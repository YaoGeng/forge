/** 只读 API 适配层（docs/18 §6 T2）——服务端字段仅在此时收口，不扩散进组件。
 * 全部为 GET 只读；生产同域 nginx Basic 自动携带凭据，dev 由 vite proxy 转发 8041。 */

export class ApiError extends Error {
  readonly status: number
  readonly path: string

  constructor(status: number, path: string) {
    super(`GET ${path} → HTTP ${status}`)
    this.status = status
    this.path = path
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    throw new ApiError(res.status, path)
  }
  return (await res.json()) as T
}

/** GET /api/v1/stats/first-run —— D-5' 首跑聚合（store.py：rate = round(ok/n, 4)） */
export interface FirstRunStat {
  app: string
  first_runs: number
  ok_first_runs: number
  rate: number
}

export const fetchFirstRunStats = () => getJson<FirstRunStat[]>('/api/v1/stats/first-run')

/** GET /api/v1/apps —— 应用列表（仅 latest 摘要；版本全列表走 E1，docs/18 §5 已核实） */
export interface AppSummary {
  id: number
  name: string
  title: string
  status: string | null
  version: string | null
}

export const fetchApps = () => getJson<AppSummary[]>('/api/v1/apps')

/** GET /api/v1/apps/{app_id}/versions —— E1 应用版本全列表（id desc） */
export interface AppVersionRow {
  id: number
  version: string
  status: string
  created_at: string
}

export const fetchAppVersions = (appId: number) =>
  getJson<AppVersionRow[]>(`/api/v1/apps/${appId}/versions`)

/** GET /api/v1/stats/run-reports?limit=50 —— E3 运行上报 / 认证记录（id desc） */
export interface RunReportRow {
  id: number
  app_name: string
  ok: boolean
  failure_class: string | null
  env_class: string
  first_run: boolean
  created_at: string
}

export const fetchRunReports = (limit = 50) =>
  getJson<RunReportRow[]>(`/api/v1/stats/run-reports?limit=${limit}`)
