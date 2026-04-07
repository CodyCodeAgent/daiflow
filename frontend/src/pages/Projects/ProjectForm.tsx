import { useState, useEffect, useCallback } from 'react'
import { useLocale } from '../../hooks/useLocale'
import { useToast } from '../../components/Toast/ToastContext'
import { listRunners, listSkills, getProjectSkills, linkProjectSkill, unlinkProjectSkill } from '../../api'
import type { RunnerConfigData, SkillBriefData } from '../../api'
import './CreateProject.css'

export interface RepoEntry {
  id?: string
  git_url: string
  local_path: string
  repo_type: string
  repo_type_label: string
  description: string
  sub_path: string
}

interface ProjectFormProps {
  projectId?: string
  initialName?: string
  initialDescription?: string
  initialRepos?: RepoEntry[]
  initialSkills?: string[]
  initialRunnerId?: string | null
  onSave: (data: { name: string; description: string; repos: RepoEntry[]; skill_names: string[]; runner_id?: string | null }) => Promise<void>
  onCancel: () => void
  saveLabel?: string
}

export default function ProjectForm({
  projectId,
  initialName = '',
  initialDescription = '',
  initialRepos,
  initialSkills = [],
  initialRunnerId = null,
  onSave,
  onCancel,
  saveLabel,
}: ProjectFormProps) {
  const { t } = useLocale()
  const toast = useToast()
  const [name, setName] = useState(initialName)
  const [description, setDescription] = useState(initialDescription)
  const [repos, setRepos] = useState<RepoEntry[]>(
    initialRepos || [{
      git_url: '', local_path: '', repo_type: 'frontend', repo_type_label: '', description: '',
      sub_path: '',
    }]
  )
  const [skillInput, setSkillInput] = useState('')
  const [skills, setSkills] = useState<string[]>(initialSkills)
  const [saving, setSaving] = useState(false)
  const [runners, setRunners] = useState<RunnerConfigData[]>([])
  const [runnerId, setRunnerId] = useState<string | null>(initialRunnerId)

  // Skill picker state (edit mode only)
  const [linkedSkills, setLinkedSkills] = useState<SkillBriefData[]>([])
  const [allSkills, setAllSkills] = useState<SkillBriefData[]>([])
  const [skillSearch, setSkillSearch] = useState('')

  const loadLinkedSkills = useCallback(() => {
    if (!projectId) return
    getProjectSkills(projectId).then(setLinkedSkills).catch(() => {})
  }, [projectId])

  useEffect(() => {
    listRunners().then(setRunners).catch(err => console.error('Failed to load runners:', err))
    listSkills({ source_type: 'manual' }).then(setAllSkills).catch(() => {})
    loadLinkedSkills()
  }, [loadLinkedSkills])

  const addRepo = () => {
    setRepos([...repos, {
      git_url: '', local_path: '', repo_type: 'backend', repo_type_label: '', description: '',
      sub_path: '',
    }])
  }

  const removeRepo = (index: number) => {
    setRepos(repos.filter((_, i) => i !== index))
  }

  const updateRepo = (index: number, field: keyof RepoEntry, value: string | number | null) => {
    setRepos(repos.map((r, i) => i === index ? { ...r, [field]: value } : r))
  }

  const addSkill = () => {
    if (skillInput.trim() && !skills.includes(skillInput.trim())) {
      setSkills([...skills, skillInput.trim()])
      setSkillInput('')
    }
  }

  const handleSave = async () => {
    if (!name.trim()) return
    setSaving(true)
    // Flush any typed-but-not-confirmed skill before saving
    const finalSkills = skillInput.trim() && !skills.includes(skillInput.trim())
      ? [...skills, skillInput.trim()]
      : skills
    try {
      await onSave({
        name: name.trim(),
        description: description.trim(),
        repos,
        skill_names: finalSkills,
        runner_id: runnerId || null,
      })
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="create-project-page">
      <div className="section-head">{t('form.basic_info')}</div>
      <div className="field">
        <label className="field-label">{t('form.project_name')}</label>
        <input className="input" placeholder={t('form.project_name_placeholder')} value={name} onChange={e => setName(e.target.value)} />
      </div>
      <div className="field">
        <label className="field-label">{t('form.description')}</label>
        <textarea className="input" rows={3} placeholder={t('form.description_placeholder')} value={description} onChange={e => setDescription(e.target.value)} />
      </div>

      <div className="section-head">{t('form.code_repos')}</div>
      {repos.map((repo, i) => (
        <div key={i} className="repo-block">
          <div className="repo-block-head">
            <div className="type-toggle">
              {['frontend', 'backend', 'fullstack', 'custom'].map(tp => (
                <button
                  key={tp}
                  className={`type-btn ${repo.repo_type === tp ? (tp === 'frontend' ? 'fe' : tp === 'backend' ? 'be' : tp === 'fullstack' ? 'fs' : 'custom') : ''}`}
                  onClick={() => updateRepo(i, 'repo_type', tp)}
                >
                  {tp}
                </button>
              ))}
            </div>
            {repos.length > 1 && (
              <button className="btn btn-danger btn-xs" onClick={() => removeRepo(i)}>{t('form.remove')}</button>
            )}
          </div>
          <div className="field-row">
            <div className="field">
              <label className="field-label">{t('form.git_url')}</label>
              <input className="input" placeholder="https://git.example.com/repo.git" value={repo.git_url} onChange={e => updateRepo(i, 'git_url', e.target.value)} />
            </div>
            <div className="field">
              <label className="field-label">{t('form.local_path')}</label>
              <input className="input" placeholder="/path/to/local/repo" value={repo.local_path} onChange={e => updateRepo(i, 'local_path', e.target.value)} />
            </div>
          </div>
          <div className="field-row">
            <div className="field" style={{ flex: 1 }}>
              <label className="field-label">{t('form.repo_desc')}</label>
              <input className="input" placeholder={t('form.repo_desc_placeholder')} value={repo.description} onChange={e => updateRepo(i, 'description', e.target.value)} />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label className="field-label">{t('form.sub_path')}</label>
              <input className="input" placeholder={t('form.sub_path_placeholder')} value={repo.sub_path} onChange={e => updateRepo(i, 'sub_path', e.target.value)} />
            </div>
          </div>
        </div>
      ))}
      <button className="add-repo-btn" onClick={addRepo}>{t('form.add_repo')}</button>

      <div className="section-head" style={{ marginTop: 28 }}>{t('form.skill_config')}</div>

      {/* Runner selector */}
      {runners.length > 0 && (
        <div className="field">
          <label className="field-label">{t('runners.select_label')}</label>
          <select
            className="input"
            value={runnerId || ''}
            onChange={e => setRunnerId(e.target.value || null)}
          >
            <option value="">
              {(() => {
                const defaultRunner = runners.find(r => r.is_default)
                return defaultRunner
                  ? `${t('runners.use_global_default')} (${defaultRunner.name})`
                  : t('runners.use_global_default')
              })()}
            </option>
            {runners.map(r => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Skill picker (edit mode) or free-text tags (create mode) */}
      {projectId ? (
        <>
          <div className="field">
            <label className="field-label">{t('form.linked_skills')}</label>
          </div>
          {linkedSkills.length > 0 && (
            <div className="skill-pills">
              {linkedSkills.map(s => (
                <span key={s.id} className="tag tag-purple">
                  {s.name}
                  <span style={{ cursor: 'pointer', marginLeft: 6 }} onClick={async () => {
                    try {
                      await unlinkProjectSkill(projectId, s.id)
                      loadLinkedSkills()
                    } catch (err: any) { toast.error(err.message) }
                  }}>x</span>
                </span>
              ))}
            </div>
          )}
          {linkedSkills.length === 0 && <div style={{ fontSize: 12, color: 'var(--t3)', marginBottom: 8 }}>{t('skills.empty')}</div>}
          <div className="field">
            <input
              className="input"
              placeholder={t('form.skill_search_placeholder')}
              value={skillSearch}
              onChange={e => setSkillSearch(e.target.value)}
            />
          </div>
          {skillSearch.trim() && (
            <div className="skill-search-results">
              {allSkills
                .filter(s => !linkedSkills.some(ls => ls.id === s.id))
                .filter(s => s.name.toLowerCase().includes(skillSearch.toLowerCase()) || s.description.toLowerCase().includes(skillSearch.toLowerCase()))
                .slice(0, 8)
                .map(s => (
                  <div key={s.id} className="skill-search-item" onClick={async () => {
                    try {
                      await linkProjectSkill(projectId, s.id)
                      loadLinkedSkills()
                      setSkillSearch('')
                    } catch (err: any) { toast.error(err.message) }
                  }}>
                    <strong>{s.name}</strong>
                    {s.description && <span className="skill-search-desc">{s.description}</span>}
                  </div>
                ))}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="field">
            <label className="field-label">{t('form.skill_names')}</label>
            <input
              className="input"
              placeholder={t('form.skill_placeholder')}
              value={skillInput}
              onChange={e => setSkillInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addSkill() } }}
            />
          </div>
          {skills.length > 0 && (
            <div className="skill-pills">
              {skills.map((s, i) => (
                <span key={i} className="tag tag-purple">
                  {s}
                  <span style={{ cursor: 'pointer', marginLeft: 6 }} onClick={() => setSkills(skills.filter((_, j) => j !== i))}>x</span>
                </span>
              ))}
            </div>
          )}
        </>
      )}

      <div className="form-footer">
        <button className="btn btn-ghost" onClick={onCancel}>{t('form.cancel')}</button>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving || !name.trim()}>
          {saving ? t('form.saving') : (saveLabel || t('form.save'))}
        </button>
      </div>
    </div>
  )
}
