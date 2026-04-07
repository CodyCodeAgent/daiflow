/**
 * Skill Center API — types and functions for skill CRUD + associations.
 */
import { request } from './index'

// ── Types ──

export interface SkillData {
  id: string
  source_type: 'project' | 'manual' | 'external'
  source_id: string
  name: string
  description: string
  content: string
  created_at: string | null
  updated_at: string | null
}

export interface SkillBriefData {
  id: string
  source_type: string
  source_id: string
  name: string
  description: string
  created_at: string | null
  updated_at: string | null
}

// ── Skill CRUD ──

export const listSkills = (params?: { source_type?: string; source_id?: string; project_id?: string }) => {
  const qs = new URLSearchParams()
  if (params?.source_type) qs.set('source_type', params.source_type)
  if (params?.source_id) qs.set('source_id', params.source_id)
  if (params?.project_id) qs.set('project_id', params.project_id)
  const query = qs.toString()
  return request<SkillBriefData[]>(`/skills${query ? `?${query}` : ''}`)
}
export const getSkill = (id: string) => request<SkillData>(`/skills/${id}`)
export const createSkill = (data: { source_type?: string; source_id?: string; name: string; description?: string; content: string }) =>
  request<SkillData>('/skills', { method: 'POST', body: JSON.stringify(data) })
export const updateSkill = (id: string, data: { description?: string; content?: string }) =>
  request<SkillData>(`/skills/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteSkill = (id: string) =>
  request<{ ok: boolean }>(`/skills/${id}`, { method: 'DELETE' })

// ── Project-skill associations ──

export const getProjectSkills = (projectId: string) =>
  request<SkillBriefData[]>(`/projects/${projectId}/skills`)
export const linkProjectSkill = (projectId: string, skillId: string) =>
  request<{ ok: boolean }>(`/projects/${projectId}/skills/${skillId}`, { method: 'POST' })
export const unlinkProjectSkill = (projectId: string, skillId: string) =>
  request<{ ok: boolean }>(`/projects/${projectId}/skills/${skillId}`, { method: 'DELETE' })

// ── Task-skill associations ──

export const getTaskSkills = (taskId: string) =>
  request<{ project_skills: SkillBriefData[]; extra_skills: SkillBriefData[] }>(`/tasks/${taskId}/skills`)
export const addTaskSkill = (taskId: string, skillId: string) =>
  request<{ ok: boolean }>(`/tasks/${taskId}/skills/${skillId}`, { method: 'POST' })
export const removeTaskSkill = (taskId: string, skillId: string) =>
  request<{ ok: boolean }>(`/tasks/${taskId}/skills/${skillId}`, { method: 'DELETE' })
