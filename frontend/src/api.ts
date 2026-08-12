import axios from 'axios'
import type { Inspection, Job, MetricRow, PreflightResult, Project } from './types'

const http = axios.create({ baseURL: '/api', timeout: 15000 })

export const api = {
  chooseDirectory: () => http.post<{ path: string }>('/system/select-directory').then(r => r.data),
  inspectProject: (path: string) => http.post<Inspection>('/projects/inspect', { path }).then(r => r.data),
  registerProject: (inspection: Inspection) => http.post<Project>('/projects', { inspection }).then(r => r.data),
  listProjects: () => http.get<Project[]>('/projects').then(r => r.data),
  preflightProject: (projectId: number, values: Record<string, unknown>) =>
    http.post<PreflightResult>(`/projects/${projectId}/preflight`, { values }).then(r => r.data),
  createExperiment: (projectId: number, name: string, values: Record<string, unknown>) =>
    http.post('/experiments', { project_id: projectId, name, values }).then(r => r.data),
  startExperiment: (id: number) => http.post<Job>(`/experiments/${id}/start`).then(r => r.data),
  listJobs: () => http.get<Job[]>('/jobs').then(r => r.data),
  getJob: (id: number) => http.get<Job>(`/jobs/${id}`).then(r => r.data),
  stopJob: (id: number) => http.post(`/jobs/${id}/stop`).then(r => r.data),
  updateControl: (id: number, values: Record<string, unknown>) =>
    http.patch(`/jobs/${id}/control`, { values }).then(r => r.data),
  getLogs: (id: number) => http.get<{ lines: string[] }>(`/jobs/${id}/logs`).then(r => r.data),
  getMetrics: (id: number) => http.get<MetricRow[]>(`/jobs/${id}/metrics`).then(r => r.data),
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) return error.response?.data?.detail || error.message
  return error instanceof Error ? error.message : String(error)
}
