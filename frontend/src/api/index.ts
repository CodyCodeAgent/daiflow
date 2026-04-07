export const BASE = '/api'

const REQUEST_TIMEOUT_MS = 30_000

export async function request<T = unknown>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      signal: controller.signal,
    })
    if (!res.ok) {
      let detail = `API error: ${res.status}`
      try {
        const body = await res.json()
        if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch {
        // Response body is not JSON — keep the status-based message
      }
      throw new Error(detail)
    }
    return res.json()
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`Request timeout: ${path}`)
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
}

export * from './skills'

// ── Types ──

export interface RunnerConfigData {
  id: string
  type: 'cody' | 'claude_code' | 'cursor'
  name: string
  config: Record<string, string>
  is_default: boolean
  created_at: string | null
  updated_at: string | null
}

export interface RunnerConfigCreateData {
  type: 'cody' | 'claude_code' | 'cursor'
  name: string
  config: Record<string, string>
}

export interface TaskData {
  id: string
  name: string
  project_id: string
  description: string
  branch: string
  prd: string
  prd_doc_url: string
  prd_images: string[]
  tech_plan: string
  tech_doc_url: string
  spec_doc: string
  status: number
  mr_info: Record<string, any>
  runner_id: string | null
  created_at: string | null
  updated_at: string | null
  run_all_in_progress?: boolean
}

export interface TodoData {
  id: string
  seq: number
  title: string
  description: string
  status: number
  cody_session_id?: string
}

export interface ProjectData {
  id: string
  name: string
  description: string
  repos?: RepoData[]
  runner_id: string | null
  created_at: string | null
  updated_at: string | null
}

export interface RepoData {
  id: string
  git_url: string
  local_path: string
  repo_type: string
  repo_type_label: string
  description: string
  sub_path: string
}

export interface SessionStatusData {
  session_id: string
  cody_session_id: string | null
  type: string
  ref_id: string
  layer: number | null
  status: number
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export interface DiffData {
  diffs: { repo: string; repo_type: string; diff: string; error?: string }[]
}

/** Extract and join raw diff strings from a DiffData response. */
export function joinDiffs(data: DiffData): string {
  return data.diffs?.map(d => d.diff).join('\n') || ''
}

interface CreateProjectData {
  name: string
  description?: string
  repos?: {
    git_url: string
    local_path?: string
    repo_type: string
    repo_type_label?: string
    description?: string
    sub_path?: string
  }[]
  runner_id?: string | null
}

interface CreateTaskData {
  name: string
  project_id: string
  description?: string
  branch?: string
  prd?: string
  prd_doc_url?: string
  tech_plan?: string
  tech_doc_url?: string
  runner_id?: string | null
}

interface UpdateTaskData {
  name?: string
  description?: string
  branch?: string
  prd?: string
  prd_doc_url?: string
  tech_plan?: string
  tech_doc_url?: string
  runner_id?: string | null
}

// ── Settings ──
export const getSettings = () => request<Record<string, string>>('/settings')
export const updateSettings = (data: Record<string, string>) =>
  request('/settings', { method: 'PUT', body: JSON.stringify(data) })
export const checkSettings = () => request<{ configured: boolean; model: string }>('/settings/check')
export const testConnection = (data: { cody_model: string; cody_base_url: string; cody_api_key: string }) =>
  request<{ ok: boolean; model: string }>('/settings/test', { method: 'POST', body: JSON.stringify(data) })

// ── Runner Configs ──
export const listRunners = () =>
  request<RunnerConfigData[]>('/settings/runners')
export const getDefaultRunner = () =>
  request<{ runner_id: string | null }>('/settings/runners/default')
export const setDefaultRunner = (runnerId: string) =>
  request<{ ok: boolean; runner_id: string }>('/settings/runners/default', {
    method: 'PUT',
    body: JSON.stringify({ runner_id: runnerId }),
  })
export const createRunner = (data: RunnerConfigCreateData) =>
  request<RunnerConfigData>('/settings/runners', { method: 'POST', body: JSON.stringify(data) })
export const updateRunner = (id: string, data: { name?: string; config?: Record<string, string> }) =>
  request<RunnerConfigData>(`/settings/runners/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteRunner = (id: string) =>
  request<{ ok: boolean }>(`/settings/runners/${id}`, { method: 'DELETE' })
export const testRunnerById = (id: string) =>
  request<{ ok: boolean; type: string }>(`/settings/runners/${id}/test`, { method: 'POST' })
export const testRunnerConfig = (data: RunnerConfigCreateData) =>
  request<{ ok: boolean; type: string }>('/settings/runners/test-config', {
    method: 'POST',
    body: JSON.stringify(data),
  })
// ── Projects ──
export const listProjects = () => request<ProjectData[]>('/projects')
export const getProject = (id: string) => request<ProjectData>(`/projects/${id}`)
export const createProject = (data: CreateProjectData) =>
  request<ProjectData>('/projects', { method: 'POST', body: JSON.stringify(data) })
export const updateProject = (id: string, data: Partial<CreateProjectData>) =>
  request<ProjectData>(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteProject = (id: string) =>
  request<{ ok: boolean }>(`/projects/${id}`, { method: 'DELETE' })
export const initProject = (id: string) =>
  request<{ ok: boolean }>(`/projects/${id}/init`, { method: 'POST' })
export interface InitLayerData {
  layer: number
  sessions: (Pick<SessionStatusData, 'session_id' | 'status' | 'error' | 'started_at' | 'finished_at'>)[]
  status: string
}
export const getInitSessions = (id: string) =>
  request<InitLayerData[]>(`/projects/${id}/init/sessions`)
export const retryProjectInit = (id: string) =>
  request<{ ok: boolean }>(`/projects/${id}/init/retry`, { method: 'POST' })

export interface InitSessionData {
  session_id: string
  status: number
  error: string | null
  started_at: string | null
  finished_at: string | null
}

// ── Tasks ──
export const listTasks = (projectId?: string) =>
  request<TaskData[]>(`/tasks${projectId ? `?project_id=${projectId}` : ''}`)
export const getTask = (id: string) => request<TaskData>(`/tasks/${id}`)
export const createTask = (data: CreateTaskData) =>
  request<TaskData>('/tasks', { method: 'POST', body: JSON.stringify(data) })
export const updateTask = (id: string, data: UpdateTaskData) =>
  request<TaskData>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteTask = (id: string) =>
  request<{ ok: boolean }>(`/tasks/${id}`, { method: 'DELETE' })
export const confirmInit = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/confirm-init`, { method: 'POST' })
export const retryTaskInit = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/retry-init`, { method: 'POST' })
export const getTaskInitSessions = (taskId: string) =>
  request<InitSessionData[]>(`/tasks/${taskId}/init/sessions`)
export const lockPlan = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/lock-plan`, { method: 'POST' })
export const startCoding = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/start-coding`, { method: 'POST' })
export const startReview = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/start-review`, { method: 'POST' })
export const triggerSpec = (id: string) =>
  request<{ ok: boolean }>(`/tasks/${id}/spec`, { method: 'POST' })
export const triggerPlan = (id: string) =>
  request<{ ok: boolean }>(`/tasks/${id}/plan`, { method: 'POST' })
export const triggerTodo = (id: string) =>
  request<{ ok: boolean }>(`/tasks/${id}/todo`, { method: 'POST' })
export const getTodos = (taskId: string) =>
  request<TodoData[]>(`/tasks/${taskId}/todos`)
export const getTaskDiff = (taskId: string) =>
  request<DiffData>(`/tasks/${taskId}/diff`)
export const generateCommitMessage = (taskId: string) =>
  request<{ commit_message: string }>(`/tasks/${taskId}/generate-commit-message`, { method: 'POST' })
export const submitMR = (taskId: string, commitMessage: string) =>
  request<{ ok: boolean; results: { repo: string; status: string; error?: string; mr_link?: string }[] }>(`/tasks/${taskId}/submit-mr`, {
    method: 'POST',
    body: JSON.stringify({ commit_message: commitMessage }),
  })

// ── PRD Images ──
export async function uploadPrdImage(taskId: string, file: File): Promise<{ filename: string }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/tasks/${taskId}/prd-images`, { method: 'POST', body: form })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Upload failed: ${res.status}`)
  }
  return res.json()
}
export const deletePrdImage = (taskId: string, filename: string) =>
  request<{ ok: boolean }>(`/tasks/${taskId}/prd-images/${filename}`, { method: 'DELETE' })
export const getPrdImageUrl = (taskId: string, filename: string) =>
  `${BASE}/tasks/${taskId}/prd-images/${filename}`

// ── Todos ──
export const executeTodo = (todoId: string) =>
  request<{ ok: boolean }>(`/todos/${todoId}/execute`, { method: 'POST' })
export const skipTodo = (todoId: string) =>
  request<{ ok: boolean }>(`/todos/${todoId}/skip`, { method: 'POST' })
export const runAllTodos = (taskId: string) =>
  request<{ ok: boolean }>(`/tasks/${taskId}/run-all-todos`, { method: 'POST' })
export const cancelRunAll = (taskId: string) =>
  request<{ ok: boolean }>(`/tasks/${taskId}/cancel-run-all`, { method: 'POST' })
export const getTodoDiff = (todoId: string) =>
  request<DiffData>(`/todos/${todoId}/diff`)

// ── Sessions ──
export const listSessions = (params?: { ref_id?: string; type?: string }) => {
  const qs = new URLSearchParams()
  if (params?.ref_id) qs.set('ref_id', params.ref_id)
  if (params?.type) qs.set('type', params.type)
  const query = qs.toString()
  return request<SessionStatusData[]>(`/sessions${query ? `?${query}` : ''}`)
}
export const getSessionStatus = (sessionId: string) =>
  request<SessionStatusData>(`/sessions/${sessionId}/status`)
export const getSessionLogs = (sessionId: string) =>
  request<Record<string, unknown>[]>(`/sessions/${sessionId}/logs`)
export const forceFailSession = (sessionId: string) =>
  request<SessionStatusData>(`/sessions/${sessionId}/force-fail`, { method: 'POST' })
export const syncSessionStatus = (sessionId: string) =>
  request<{ message: string }>(`/sessions/${sessionId}/sync-status`, { method: 'POST' })

// ── Jobs ──
export interface JobData {
  id: string
  project_id: string
  type: string
  enabled: boolean
  interval: number
  config: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface JobRunData {
  id: string
  job_id: string
  status: string
  result: Record<string, unknown>
  error: string | null
  started_at: string | null
  finished_at: string | null
  project_id?: string
  job_type?: string
}

export const listJobs = (projectId?: string) =>
  request<JobData[]>(`/jobs${projectId ? `?project_id=${projectId}` : ''}`)
export const getJobRuns = (jobId: string, limit = 50) =>
  request<JobRunData[]>(`/jobs/${jobId}/runs?limit=${limit}`)

// ── MCP Servers ──
export interface McpServerData {
  id: string
  name: string
  url: string
  headers: Record<string, string>
  enabled: boolean
  created_at: string | null
  updated_at: string | null
}

export const listMcpServers = () =>
  request<McpServerData[]>('/settings/mcp-servers')
export const createMcpServer = (data: { name: string; url: string; headers?: Record<string, string>; enabled?: boolean }) =>
  request<McpServerData>('/settings/mcp-servers', { method: 'POST', body: JSON.stringify(data) })
export const updateMcpServer = (id: string, data: { name?: string; url?: string; headers?: Record<string, string>; enabled?: boolean }) =>
  request<McpServerData>(`/settings/mcp-servers/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteMcpServer = (id: string) =>
  request<{ ok: boolean }>(`/settings/mcp-servers/${id}`, { method: 'DELETE' })
export const testMcpServer = (data: { url: string; headers?: Record<string, string> }) =>
  request<{ ok: boolean; server_name: string; server_version: string; protocol_version: string }>(
    '/settings/mcp-servers/test', { method: 'POST', body: JSON.stringify(data) }
  )

// ── Conversations ──
export interface ConversationData {
  id: string
  name: string
  project_id: string
  description: string
  status: number
  runner_id: string | null
  created_at: string | null
  updated_at: string | null
}

export const listConversations = (projectId?: string) =>
  request<ConversationData[]>(`/conversations${projectId ? `?project_id=${projectId}` : ''}`)
export const getConversation = (id: string) =>
  request<ConversationData>(`/conversations/${id}`)
export const createConversation = (data: { name: string; project_id: string; description?: string; runner_id?: string | null }) =>
  request<ConversationData>('/conversations', { method: 'POST', body: JSON.stringify(data) })
export const deleteConversation = (id: string) =>
  request<{ ok: boolean }>(`/conversations/${id}`, { method: 'DELETE' })
export const retryConversationInit = (id: string) =>
  request<{ ok: boolean }>(`/conversations/${id}/retry-init`, { method: 'POST' })
export const getConversationInitSessions = (convId: string) =>
  request<{ session_id: string; type: string; status: number; error: string | null }[]>(`/conversations/${convId}/init/sessions`)

// ── Task Files (for @ mention) ──
export const listTaskFiles = (taskId: string, prefix = '') =>
  request<{ files: string[] }>(`/tasks/${taskId}/files?prefix=${encodeURIComponent(prefix)}&limit=30`)

// ── Chat Attachments (images) ──
export async function uploadChatImage(taskId: string, file: File): Promise<{ path: string }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/tasks/${taskId}/attachments`, { method: 'POST', body: form })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Upload failed: ${res.status}`)
  }
  return res.json()
}

// ── Artifact API ──
export type ArtifactName = 'plan' | 'spec' | 'research' | 'data-model' | 'tasks'

export interface ArtifactResponse {
  content: string
  exists: boolean
}

export const getTaskArtifact = (taskId: string, name: ArtifactName): Promise<ArtifactResponse> =>
  request<ArtifactResponse>(`/tasks/${taskId}/artifacts/${name}`)


