import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import {
  listConversations,
  deleteConversation,
  createConversation,
  listProjects,
} from '../../api'
import type { ConversationData, ProjectData } from '../../api'
import { ConversationStatus } from '../../types/enums'
import { useLocale } from '../../hooks/useLocale'
import { useToast } from '../../components/Toast/ToastContext'
import type { TranslationKey } from '../../i18n'
import './Conversations.css'

const STATUS_CLS: Record<number, string> = {
  [ConversationStatus.CREATING]: 'tag-amber',
  [ConversationStatus.READY]: 'tag-green',
  [ConversationStatus.FAILED]: 'tag-red',
}

export default function Conversations() {
  const navigate = useNavigate()
  const { t } = useLocale()
  const toast = useToast()

  const [conversations, setConversations] = useState<ConversationData[]>([])
  const [projects, setProjects] = useState<ProjectData[]>([])
  const [showForm, setShowForm] = useState(false)

  // Form state
  const [name, setName] = useState('')
  const [projectId, setProjectId] = useState('')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)

  const load = () => {
    listConversations().then(setConversations).catch(() => {})
  }

  useEffect(() => {
    load()
    listProjects().then(setProjects).catch(() => {})
  }, [])

  const projectName = (pid: string) => projects.find(p => p.id === pid)?.name || pid.slice(0, 8)

  const handleCreate = async () => {
    if (!name.trim() || !projectId) return
    setCreating(true)
    try {
      const conv = await createConversation({ name: name.trim(), project_id: projectId, description })
      setConversations(prev => [conv, ...prev])
      setShowForm(false)
      setName('')
      setProjectId('')
      setDescription('')
      // Navigate immediately — the chat page will show init progress
      navigate(`/conversations/${conv.id}`)
    } catch (err: any) {
      toast.error(err.message || t('toast.operation_failed'))
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm(t('conversations.delete_confirm'))) return
    try {
      await deleteConversation(id)
      setConversations(prev => prev.filter(c => c.id !== id))
    } catch (err: any) {
      toast.error(err.message || t('toast.operation_failed'))
    }
  }

  const handleClick = (conv: ConversationData) => {
    navigate(`/conversations/${conv.id}`)
  }

  return (
    <>
      <Topbar title={t('conversations.title')} />
      <div className="page-body">
        <div className="page-header">
          <h2>{t('conversations.title')}</h2>
          <button className="btn-primary" onClick={() => setShowForm(true)}>
            {t('conversations.new')}
          </button>
        </div>

        {showForm && (
          <div className="conv-form">
            <div className="form-field">
              <label>{t('conversations.name')}</label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder={t('conversations.name_placeholder')}
                autoFocus
              />
            </div>
            <div className="form-field">
              <label>{t('conversations.project')}</label>
              <select value={projectId} onChange={e => setProjectId(e.target.value)}>
                <option value="">{t('conversations.select_project')}</option>
                {projects.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>{t('conversations.description')}</label>
              <input
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder={t('conversations.desc_placeholder')}
              />
            </div>
            <div className="form-actions">
              <button className="btn-secondary" onClick={() => setShowForm(false)}>
                {t('conversations.cancel')}
              </button>
              <button
                className="btn-primary"
                disabled={!name.trim() || !projectId || creating}
                onClick={handleCreate}
              >
                {creating ? t('conversations.creating') : t('conversations.create')}
              </button>
            </div>
          </div>
        )}

        {conversations.length === 0 && !showForm ? (
          <div className="empty-state">{t('conversations.empty')}</div>
        ) : (
          <div className="conv-list">
            {conversations.map(conv => (
              <div key={conv.id} className="conv-row" onClick={() => handleClick(conv)}>
                <div className="conv-left">
                  <div className="conv-name">{conv.name}</div>
                  <div className="conv-info">
                    <span className="conv-project">{projectName(conv.project_id)}</span>
                    {conv.description && <span className="conv-desc">{conv.description}</span>}
                    {conv.created_at && (
                      <span className="conv-time">{new Date(conv.created_at).toLocaleDateString()}</span>
                    )}
                  </div>
                </div>
                <div className="conv-right">
                  <span className={`status-tag ${STATUS_CLS[conv.status] || 'tag-dim'}`}>
                    {t(`conversations.status.${conv.status}` as TranslationKey)}
                  </span>
                  <button
                    className="btn-icon-sm"
                    onClick={e => { e.stopPropagation(); handleDelete(conv.id) }}
                    title={t('projects.delete')}
                  >
                    &times;
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
