import { useState, useEffect, useCallback } from 'react'
import Topbar from '../../components/Shell/Topbar'
import {
  listSkills, getSkill, createSkill, updateSkill, deleteSkill,
  type SkillBriefData, type SkillData,
} from '../../api'
import { useLocale } from '../../hooks/useLocale'
import { useToast } from '../../components/Toast/ToastContext'
import './Skills.css'

type FilterType = 'all' | 'project' | 'manual' | 'external'

function SkillForm({ initial, onSave, onCancel, t }: {
  initial?: { name: string; description: string; content: string; source_type?: string }
  onSave: (data: { name: string; description: string; content: string; source_type: string }) => void
  onCancel: () => void
  t: (k: any) => string
}) {
  const [name, setName] = useState(initial?.name || '')
  const [description, setDescription] = useState(initial?.description || '')
  const [content, setContent] = useState(initial?.content || '')
  const isEdit = !!initial?.name

  return (
    <div className="skill-form">
      {!isEdit && (
        <div className="field">
          <label className="field-label">{t('skills.name')}</label>
          <input className="input" value={name} onChange={e => setName(e.target.value)}
            placeholder={t('skills.name_placeholder')} />
        </div>
      )}
      <div className="field">
        <label className="field-label">{t('skills.description')}</label>
        <input className="input" value={description} onChange={e => setDescription(e.target.value)}
          placeholder={t('skills.desc_placeholder')} />
      </div>
      <div className="field">
        <label className="field-label">{t('skills.content')}</label>
        <textarea className="input skill-content-input" value={content} onChange={e => setContent(e.target.value)}
          placeholder={t('skills.content_placeholder')} rows={10} />
      </div>
      <div className="actions">
        <button className="btn btn-primary btn-sm" onClick={() => onSave({ name, description, content, source_type: 'manual' })}
          disabled={!name.trim()}>{t('skills.save')}</button>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>{t('skills.cancel')}</button>
      </div>
    </div>
  )
}

export default function Skills() {
  const { t } = useLocale()
  const toast = useToast()
  const [skills, setSkills] = useState<SkillBriefData[]>([])
  const [filter, setFilter] = useState<FilterType>('all')
  const [selected, setSelected] = useState<SkillData | null>(null)
  const [editing, setEditing] = useState<string | null>(null) // 'new' | skill_id | null
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    const params = filter !== 'all' ? { source_type: filter } : undefined
    listSkills(params).then(setSkills).catch(err => console.error('Failed to load skills:', err))
  }, [filter])

  useEffect(() => { load() }, [load])

  const handleSelect = async (s: SkillBriefData) => {
    if (editing) return
    setLoading(true)
    try {
      const full = await getSkill(s.id)
      setSelected(full)
    } catch (err: any) { toast.error(err.message) }
    finally { setLoading(false) }
  }

  const handleCreate = async (data: { name: string; description: string; content: string; source_type: string }) => {
    try {
      await createSkill({ source_type: 'manual', source_id: '0', name: data.name, description: data.description, content: data.content })
      setEditing(null)
      load()
      toast.success(t('skills.created'))
    } catch (err: any) { toast.error(err.message) }
  }

  const handleUpdate = async (data: { name: string; description: string; content: string }) => {
    if (!selected) return
    try {
      const updated = await updateSkill(selected.id, { description: data.description, content: data.content })
      setSelected(updated)
      setEditing(null)
      load()
      toast.success(t('skills.updated'))
    } catch (err: any) { toast.error(err.message) }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteSkill(id)
      if (selected?.id === id) setSelected(null)
      load()
      toast.success(t('skills.deleted'))
    } catch (err: any) { toast.error(err.message) }
  }

  const sourceLabel = (s: SkillBriefData) => {
    if (s.source_type === 'project') return t('skills.source_project')
    if (s.source_type === 'external') return t('skills.source_external')
    return t('skills.source_manual')
  }

  return (
    <>
      <Topbar
        title={t('skills.title')}
        actions={
          editing !== 'new' ? (
            <button className="btn btn-primary btn-sm" onClick={() => {
              setEditing('new')
              setSelected(null)
            }}>{t('skills.add')}</button>
          ) : undefined
        }
      />
      <div className="content">
        <div className="skills-page">
          <p className="page-desc">{t('skills.page_desc')}</p>

          {/* Filter tabs */}
          <div className="skill-filters">
            {(['all', 'project', 'manual', 'external'] as FilterType[]).map(f => (
              <button key={f} className={`btn btn-sm ${filter === f ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => { setFilter(f); setSelected(null); setEditing(null) }}>
                {t(`skills.filter_${f}`)}
              </button>
            ))}
          </div>

          <div className="skill-layout">
            {/* List */}
            <div className="skill-list">
              {editing === 'new' && (
                <div className="card skill-card skill-card-form">
                  <SkillForm t={t} onSave={handleCreate} onCancel={() => setEditing(null)} />
                </div>
              )}

              {skills.length === 0 && editing !== 'new' && (
                <div className="skill-empty">{t('skills.empty')}</div>
              )}

              {skills.map(s => (
                <div key={s.id}
                  className={`card skill-card ${selected?.id === s.id ? 'skill-card-active' : ''}`}
                  onClick={() => handleSelect(s)}
                >
                  <div className="skill-card-header">
                    <strong className="skill-card-name">{s.name}</strong>
                    <span className={`skill-source-tag source-${s.source_type}`}>{sourceLabel(s)}</span>
                  </div>
                  {s.description && <div className="skill-card-desc">{s.description}</div>}
                  <div className="skill-card-meta">
                    {s.updated_at && <span>{new Date(s.updated_at).toLocaleDateString()}</span>}
                  </div>
                </div>
              ))}
            </div>

            {/* Detail panel */}
            <div className="skill-detail">
              {loading && <div className="skill-loading">{t('skills.loading')}</div>}
              {!loading && selected && editing !== selected.id && (
                <>
                  <div className="skill-detail-header">
                    <h3>{selected.name}</h3>
                    <div className="skill-detail-actions">
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditing(selected.id)}>{t('skills.edit')}</button>
                      <button className="btn btn-ghost btn-sm btn-danger" onClick={() => handleDelete(selected.id)}>{t('skills.delete')}</button>
                    </div>
                  </div>
                  {selected.description && <p className="skill-detail-desc">{selected.description}</p>}
                  <div className="skill-source-info">
                    <span className={`skill-source-tag source-${selected.source_type}`}>{sourceLabel(selected as any)}</span>
                    {selected.source_type === 'project' && <span className="skill-source-id">ID: {selected.source_id}</span>}
                  </div>
                  <pre className="skill-detail-content">{selected.content}</pre>
                </>
              )}
              {!loading && selected && editing === selected.id && (
                <div className="card skill-card-form">
                  <SkillForm
                    initial={{ name: selected.name, description: selected.description, content: selected.content }}
                    t={t}
                    onSave={handleUpdate}
                    onCancel={() => setEditing(null)}
                  />
                </div>
              )}
              {!loading && !selected && editing !== 'new' && (
                <div className="skill-detail-empty">{t('skills.select_hint')}</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
