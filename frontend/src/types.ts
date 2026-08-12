export interface ParameterDefinition {
  key: string
  label: string
  flag?: string | null
  type: 'integer' | 'number' | 'string' | 'boolean' | 'array'
  default: unknown
  required?: boolean
  choices?: unknown[] | null
  help?: string
  minimum?: number
  maximum?: number
  runtime_editable?: boolean
  read_only?: boolean
}

export interface Adapter {
  mode: 'automatic' | 'explicit'
  framework: string
  entrypoint: string
  python: string
  parameters: ParameterDefinition[]
}

export interface Inspection {
  name: string
  path: string
  framework: string
  entrypoint: string
  adapter: Adapter
  warnings: string[]
}

export interface Project extends Omit<Inspection, 'warnings'> {
  id: number
  created_at: string
}

export interface PreflightIssue {
  level: 'info' | 'warning' | 'error'
  code: string
  message: string
  parameter?: string
  original?: unknown
  suggested?: unknown
}

export interface PreflightChange {
  parameter: string
  original: unknown
  suggested: unknown
  reason: string
}

export interface PreflightResult {
  ok: boolean
  values: Record<string, unknown>
  issues: PreflightIssue[]
  changes: PreflightChange[]
}

export interface Job {
  id: number
  experiment_id: number
  experiment_name?: string
  project_name?: string
  pid?: number
  status: string
  run_dir: string
  started_at?: string
  finished_at?: string
  exit_code?: number
}

export interface MetricRow {
  name: string
  value: number
  epoch?: number
  step?: number
  recorded_at: string
}
