import { useState, useEffect, useCallback } from 'react'
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
  const [showDrawer, setShowDrawer] = useState(false)

  // Form state
  const [name, setName] = useState('')
  const [projectId, setProjectId] = useState('')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)

  const load = useCallback(() => {
    listConversations().then(setConversations).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    listProjects().then(setProjects).catch(() => {})
  }, [load])

  const projectName = (pid: string) => projects.find(p => p.id === pid)?.name || pid.slice(0, 8)

  const resetForm = () => {
    setName('')
    setProjectId('')
    setDescription('')
    setShowDrawer(false)
  }

  const handleCreate = async () => {
    if (!name.trim() || !projectId) return
    setCreating(true)
    try {
      const conv = await createConversation({ name: name.trim(), project_id: projectId, description })
      resetForm()
      navigate(`/conversations/${conv.id}`)
    } catch (err: any) {
      toast.error(err.message || t('toast.operation_failed'))
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(t('conversations.delete_confirm'))) return
    try {
      await deleteConversation(id)
      setConversations(prev => prev.filter(c => c.id !== id))
    } catch (err: any) {
      toast.error(err.message || t('toast.operation_failed'))
    }
  }

  return (
    <>
      <Topbar
        title={t('conversations.title')}
        actions={
          <button className="btn btn-primary btn-sm" onClick={() => setShowDrawer(true)}>
            {t('conversations.new')}
          </button>
        }
      />
      <div className="content">
        <div className="conv-list">
          {conversations.map(conv => (
            <div key={conv.id} className="conv-row" onClick={() => navigate(`/conversations/${conv.id}`)}>
              <div>
                <div className="conv-name">{conv.name}</div>
                <div className="conv-info">
                  <span className="conv-project">{projectName(conv.project_id)}</span>
                  {conv.description && <span className="conv-desc">{conv.description}</span>}
                  <span className="conv-time">{conv.created_at ? new Date(conv.created_at).toLocaleDateString() : ''}</span>
                </div>
              </div>
              <div className="conv-right">
                <span className={`tag ${STATUS_CLS[conv.status] || 'tag-dim'}`}>
                  {t(`conversations.status.${conv.status}` as TranslationKey)}
                </span>
                <button className="btn btn-danger btn-xs" onClick={e => handleDelete(conv.id, e)}>×</button>
              </div>
            </div>
          ))}
          {conversations.length === 0 && (
            <div className="conv-empty">
              <div className="conv-empty-icon">&#9993;</div>
              <p>{t('conversations.empty')}</p>
            </div>
          )}
        </div>
      </div>

      {/* New Conversation Drawer */}
      {showDrawer && (
        <>
          <div className="overlay" onClick={resetForm} />
          <div className="drawer conv-drawer">
            <div className="drawer-header">
              <span className="drawer-title">{t('conversations.new')}</span>
              <button className="drawer-close" onClick={resetForm}>×</button>
            </div>
            <div className="drawer-body">
              <div className="field">
                <label className="field-label">{t('conversations.name')}</label>
                <input
                  className="input"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder={t('conversations.name_placeholder')}
                  autoFocus
                />
              </div>
              <div className="field">
                <label className="field-label">{t('conversations.project')}</label>
                <select className="input" value={projectId} onChange={e => setProjectId(e.target.value)}>
                  <option value="">{t('conversations.select_project')}</option>
                  {projects.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label">{t('conversations.description')} <span className="field-optional">{t('tasks.doc_link_optional')}</span></label>
                <textarea
                  className="input"
                  rows={3}
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  placeholder={t('conversations.desc_placeholder')}
                />
              </div>
            </div>
            <div className="drawer-footer">
              <div />
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-ghost" onClick={resetForm}>
                  {t('conversations.cancel')}
                </button>
                <button
                  className="btn btn-primary"
                  disabled={!name.trim() || !projectId || creating}
                  onClick={handleCreate}
                >
                  {creating ? t('conversations.creating') : t('conversations.create')}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  )
}
