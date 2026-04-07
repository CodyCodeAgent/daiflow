import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import ChatPanel from '../../components/ChatPanel/ChatPanel'
import ResizableSplitPane from '../../components/ResizableSplitPane/ResizableSplitPane'
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

  const sessionId = conversationId ? sessionIds.conversationChat(conversationId) : null

  // Load conversation + project + skills
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

  // Poll while init is in progress
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

      <div className="conv-chat-body">
        <ResizableSplitPane
          right={
            <ChatPanel
              messages={messages}
              onSend={sendMessage}
              responding={streaming}
              cancelling={cancelling}
              onStop={stopGeneration}
              title={t('conversations.chat_title')}
              disabled={!isReady}
            />
          }
          initialRightWidth={480}
          minRightWidth={320}
        >
          {/* Left: Project Context Sidebar */}
          <div className="conv-context">
            <div className="conv-context-section">
              <h3 className="conv-context-title">{t('conversations.project')}</h3>
              <div className="conv-context-project-name">{project?.name}</div>
              {project?.description && (
                <p className="conv-context-desc">{project.description}</p>
              )}
            </div>

            {repos.length > 0 && (
              <div className="conv-context-section">
                <h3 className="conv-context-title">{t('form.code_repos')}</h3>
                <div className="conv-context-repos">
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
              <div className="conv-context-section">
                <h3 className="conv-context-title">{t('nav.skills')} ({skills.length})</h3>
                <div className="conv-context-skills">
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
              <div className="conv-context-section">
                <h3 className="conv-context-title">{t('conversations.description')}</h3>
                <p className="conv-context-desc">{conv.description}</p>
              </div>
            )}
          </div>
        </ResizableSplitPane>
      </div>
    </div>
  )
}
