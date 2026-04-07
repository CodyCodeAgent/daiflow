import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import ChatPanel from '../../components/ChatPanel/ChatPanel'
import Loading from '../../components/Loading/Loading'
import { getConversation, getProject, getConversationInitSessions, retryConversationInit } from '../../api'
import type { ConversationData, ProjectData } from '../../api'
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
  const [loading, setLoading] = useState(true)

  const sessionId = conversationId ? sessionIds.conversationChat(conversationId) : null

  // Load conversation + project
  const loadConv = useCallback(async () => {
    if (!conversationId) return
    try {
      const c = await getConversation(conversationId)
      setConv(c)
      const p = await getProject(c.project_id)
      setProject(p)
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

  return (
    <>
      <Topbar
        title={conv.name}
        subtitle={project?.name}
        backTo="/conversations"
        backLabel={t('conversations.back')}
      />
      <div className="conversation-chat-page">
        {isCreating && (
          <div className="conv-init-banner">
            <div className="conv-init-spinner" />
            <span>{t('conversations.initializing')}</span>
          </div>
        )}
        {isFailed && (
          <div className="conv-init-banner conv-init-failed">
            <span>{t('conversations.init_failed')}</span>
            <button className="btn-secondary" onClick={handleRetry}>
              {t('conversations.retry')}
            </button>
          </div>
        )}
        <div className="conversation-chat-body">
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
      </div>
    </>
  )
}
