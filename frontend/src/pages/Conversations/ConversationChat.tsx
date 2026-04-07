import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import ChatPanel from '../../components/ChatPanel/ChatPanel'
import Loading from '../../components/Loading/Loading'
import { getConversation, getProject, retryConversationInit } from '../../api'
import { getProjectSkills } from '../../api/skills'
import type { ConversationData, ProjectData, RepoData } from '../../api'
import type { SkillBriefData } from '../../api/skills'
import { ConversationStatus } from '../../types/enums'
import { useStageChat } from '../../hooks/useStageChat'
import { sessionIds } from '../../utils/sessionIds'
import { useLocale } from '../../hooks/useLocale'
import { useToast } from '../../components/Toast/ToastContext'
import './ConversationChat.css'

export default function ConversationChat() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const { t } = useLocale()
  const toast = useToast()

  const [conv, setConv] = useState<ConversationData | null>(null)
  const [project, setProject] = useState<ProjectData | null>(null)
  const [skills, setSkills] = useState<SkillBriefData[]>([])
  const [loading, setLoading] = useState(true)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const sessionId = conversationId ? sessionIds.conversationChat(conversationId) : null

  const loadConv = useCallback(async () => {
    if (!conversationId) return
    try {
      const c = await getConversation(conversationId)
      setConv(c)
      const p = await getProject(c.project_id)
      setProject(p)
      getProjectSkills(c.project_id).then(setSkills).catch(() => {})
    } catch {
      navigate('/conversations')
    } finally {
      setLoading(false)
    }
  }, [conversationId, navigate])

  useEffect(() => { loadConv() }, [loadConv])

  useEffect(() => {
    if (!conv || conv.status !== ConversationStatus.CREATING) return
    const timer = setInterval(async () => {
      try {
        const c = await getConversation(conv.id)
        setConv(c)
        if (c.status !== ConversationStatus.CREATING) clearInterval(timer)
      } catch {
        clearInterval(timer)
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [conv?.id, conv?.status])

  useEffect(() => {
    if (!drawerOpen) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrawerOpen(false) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [drawerOpen])

  const { messages, sendMessage, streaming, cancelling, stopGeneration } = useStageChat({
    sessionId: conv?.status === ConversationStatus.READY ? sessionId : null,
    stage: 'conversation',
    entityId: conversationId || '',
  })

  const handleRetry = async () => {
    if (!conversationId) return
    try {
      await retryConversationInit(conversationId)
      loadConv()
    } catch (err: any) {
      toast.error(err.message || t('toast.operation_failed'))
    }
  }

  if (loading) return <Loading />
  if (!conv) return null

  const isReady = conv.status === ConversationStatus.READY
  const isFailed = conv.status === ConversationStatus.FAILED
  const isCreating = conv.status === ConversationStatus.CREATING
  const repos = project?.repos || []

  return (
    <div className="conv-chat-page">
      <Topbar
        title={conv.name}
        subtitle={project?.name}
        backTo="/conversations"
        backLabel={t('conversations.back')}
      />

      {isCreating && (
        <div className="conv-init-banner">
          <div className="conv-init-spinner" />
          <span>{t('conversations.initializing')}</span>
        </div>
      )}
      {isFailed && (
        <div className="conv-init-banner conv-init-failed">
          <span>{t('conversations.init_failed')}</span>
          <button className="btn btn-ghost btn-sm" onClick={handleRetry}>
            {t('conversations.retry')}
          </button>
        </div>
      )}

      {/* Chat fills the full body */}
      <div className="conv-chat-body">
        <ChatPanel
          messages={messages}
          onSend={sendMessage}
          responding={streaming}
          cancelling={cancelling}
          onStop={stopGeneration}
          title={t('conversations.chat_title')}
          disabled={!isReady}
        />
      </div>

      {/* Floating trigger — position:fixed, left edge, same pattern as TaskInfoDrawer */}
      <button className="conv-ctx-trigger" onClick={() => setDrawerOpen(true)} title={t('conversations.project')}>
        <span className="conv-ctx-trigger-icon">☰</span>
        <span className="conv-ctx-trigger-label">{t('conversations.project')}</span>
      </button>

      {/* Backdrop */}
      {drawerOpen && <div className="conv-ctx-backdrop" onClick={() => setDrawerOpen(false)} />}

      {/* Drawer — position:fixed, slides in from left */}
      <div className={`conv-ctx-drawer ${drawerOpen ? 'open' : ''}`}>
        <div className="conv-ctx-drawer-header">
          <div className="conv-ctx-drawer-title">{t('conversations.project')}</div>
          <button className="conv-ctx-close-btn" onClick={() => setDrawerOpen(false)}>✕</button>
        </div>
        <div className="conv-ctx-drawer-body">

          <div className="conv-ctx-section">
            <div className="conv-ctx-project-name">{project?.name}</div>
            {project?.description && (
              <p className="conv-ctx-desc">{project.description}</p>
            )}
          </div>

          {repos.length > 0 && (
            <div className="conv-ctx-section">
              <h3 className="conv-ctx-title">{t('form.code_repos')}</h3>
              <div className="conv-ctx-repos">
                {repos.map((r: RepoData) => (
                  <div key={r.id} className="conv-repo-item">
                    <span className="conv-repo-type">{r.repo_type}</span>
                    <span className="conv-repo-url">{r.local_path || r.git_url}</span>
                    {r.description && <span className="conv-repo-desc">{r.description}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {skills.length > 0 && (
            <div className="conv-ctx-section">
              <h3 className="conv-ctx-title">{t('nav.skills')} ({skills.length})</h3>
              <div className="conv-ctx-skills">
                {skills.map(s => (
                  <div key={s.id} className="conv-skill-item">
                    <span className="conv-skill-name">{s.name}</span>
                    {s.description && <span className="conv-skill-desc">{s.description}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {conv.description && (
            <div className="conv-ctx-section">
              <h3 className="conv-ctx-title">{t('conversations.description')}</h3>
              <p className="conv-ctx-desc">{conv.description}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
