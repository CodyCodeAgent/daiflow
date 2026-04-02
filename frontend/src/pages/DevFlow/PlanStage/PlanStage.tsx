import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import StageLayout, { isStageReadonly } from '../../../components/StageLayout/StageLayout'
import MarkdownViewer from '../../../components/MarkdownViewer/MarkdownViewer'
import { usePlanStage } from '../../../hooks/usePlanStage'
import { lockPlan, triggerPlan, triggerSpec, getTaskArtifact, type ArtifactResponse } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import { useToast } from '../../../components/Toast/ToastContext'

type ArtifactTab = 'spec' | 'plan' | 'research' | 'data-model'

const TAB_LABELS: Record<ArtifactTab, string> = {
  spec: 'spec.tab',
  plan: 'plan.tab',
  research: 'artifact.research',
  'data-model': 'artifact.data_model',
}

export default function PlanStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const toast = useToast()
  const { task, planContent, status, messages, sendMessage, responding, cancelling, stopGeneration, regenerating, refreshSession, isStale, spec } = usePlanStage(taskId)

  const readonly = task ? isStageReadonly(task.status, 2) : false
  const [activeTab, setActiveTab] = useState<ArtifactTab>('spec')
  const [researchArtifact, setResearchArtifact] = useState<ArtifactResponse | null>(null)
  const [dataModelArtifact, setDataModelArtifact] = useState<ArtifactResponse | null>(null)
  const [loadingArtifacts, setLoadingArtifacts] = useState(false)

  const hasSpec = !!spec.specContent
  const specGenerating = spec.generating
  const specError = spec.specError

  // Auto-advance to plan tab once plan is available
  useEffect(() => {
    if (planContent && activeTab === 'spec' && hasSpec) {
      setActiveTab('plan')
    }
  }, [planContent])

  // Load side artifacts whenever plan content changes
  useEffect(() => {
    if (!taskId || !planContent) return
    setLoadingArtifacts(true)
    Promise.all([
      getTaskArtifact(taskId, 'research'),
      getTaskArtifact(taskId, 'data-model'),
    ]).then(([res, dm]) => {
      setResearchArtifact(res)
      setDataModelArtifact(dm)
    }).catch(() => {
      // Artifacts are optional — ignore errors
    }).finally(() => setLoadingArtifacts(false))
  }, [taskId, planContent])

  const handleRegenerate = async () => {
    if (!taskId) return
    if (!hasSpec && !readonly) {
      toast.error(t('plan.blocked_by_spec'))
      return
    }
    await triggerPlan(taskId)
    refreshSession()
    setActiveTab('plan')
  }

  const handleLockPlan = async () => {
    if (!taskId) return
    try {
      await lockPlan(taskId)
      navigate(`/devflow/${taskId}/todo`)
    } catch (err: any) {
      toast.error(err.message || t('toast.operation_failed'))
    }
  }

  const handleGenerateSpec = async () => {
    if (!taskId) return
    try {
      await triggerSpec(taskId)
      spec.refreshSpecSession()
      setActiveTab('spec')
    } catch (err: any) {
      toast.error(err.message || t('toast.operation_failed'))
    }
  }

  const isGenerating = responding || regenerating
  const lockDisabled = !planContent || isGenerating || readonly
  const regenerateDisabled = isGenerating || readonly || (!hasSpec && !readonly)
  const useSpecChat = activeTab === 'spec'

  // Determine which tabs to show
  const visibleTabs: ArtifactTab[] = ['spec', 'plan']
  if (researchArtifact?.exists) visibleTabs.push('research')
  if (dataModelArtifact?.exists) visibleTabs.push('data-model')

  const getTabContent = () => {
    switch (activeTab) {
      case 'spec':
        return renderSpecTab()
      case 'plan':
        return renderPlanTab()
      case 'research':
        return researchArtifact?.content
          ? <MarkdownViewer content={researchArtifact.content} />
          : <EmptyArtifact label={t('artifact.research')} />
      case 'data-model':
        return dataModelArtifact?.content
          ? <MarkdownViewer content={dataModelArtifact.content} />
          : <EmptyArtifact label={t('artifact.data_model')} />
      default:
        return null
    }
  }

  const renderSpecTab = () => {
    if (hasSpec) {
      return (
        <>
          <MarkdownViewer content={spec.specContent} />
          {!specGenerating && !readonly && (
            <div style={{ marginTop: '12px' }}>
              <button className="btn btn-ghost btn-xs" onClick={handleGenerateSpec} disabled={readonly}>
                {t('spec.regenerate')}
              </button>
            </div>
          )}
        </>
      )
    }
    if (specGenerating) {
      return (
        <div style={{ color: 'var(--t3)', textAlign: 'center', padding: '24px' }}>
          <div className="typing-row" style={{ justifyContent: 'center' }}>
            <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
          </div>
          <div style={{ marginTop: 8, fontSize: '13px' }}>{t('spec.generating')}</div>
        </div>
      )
    }
    return (
      <div style={{ padding: '24px 0' }}>
        {!!specError && (
          <div style={{
            marginBottom: '10px',
            padding: '10px 12px',
            borderRadius: '8px',
            fontSize: '12px',
            lineHeight: 1.5,
            color: 'var(--red)',
            background: 'var(--red-d)',
            border: '1px solid rgba(248,113,113,.35)',
            whiteSpace: 'pre-wrap',
          }}>
            {String(specError)}
          </div>
        )}
        <p style={{ marginBottom: '8px', fontSize: '13px', color: 'var(--t2)' }}>{t('spec.required_hint')}</p>
        <p style={{ marginBottom: '16px', fontSize: '12px', color: 'var(--t3)' }}>{t('spec.hint')}</p>
        <button
          className="btn btn-primary"
          onClick={handleGenerateSpec}
          disabled={specGenerating || readonly}
        >
          {t('spec.generate')}
        </button>
      </div>
    )
  }

  const renderPlanTab = () => {
    if (!hasSpec && !readonly) {
      return (
        <div style={{ padding: '32px 0', textAlign: 'center' }}>
          <div style={{ fontSize: '28px', marginBottom: '12px' }}>🔒</div>
          <p style={{ fontSize: '14px', color: 'var(--t2)', marginBottom: '8px' }}>{t('plan.blocked_by_spec')}</p>
          <button className="btn btn-primary" onClick={() => setActiveTab('spec')}>
            {t('spec.generate')}
          </button>
        </div>
      )
    }
    if (planContent) {
      return <MarkdownViewer content={planContent} />
    }
    return (
      <div style={{ color: 'var(--t3)', textAlign: 'center', padding: '40px' }}>
        {status === 1 ? (
          <>
            <div className="typing-row" style={{ justifyContent: 'center' }}>
              <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
            </div>
            <div style={{ marginTop: 8, fontSize: '13px' }}>{t('plan.generating')}</div>
          </>
        ) : (
          <p style={{ fontSize: '13px' }}>{t('plan.generating')}</p>
        )}
      </div>
    )
  }

  return (
    <StageLayout
      taskId={taskId!}
      task={task}
      currentStage={2}
      content={
        <div className="card plan-card">
          {/* Tab bar */}
          <div className="plan-tabs" style={{ display: 'flex', gap: '4px', marginBottom: '16px', borderBottom: '1px solid var(--border)', paddingBottom: '0' }}>
            {visibleTabs.map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`plan-tab-btn ${activeTab === tab ? 'active' : ''}`}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: '8px 14px',
                  fontSize: '13px',
                  cursor: 'pointer',
                  color: activeTab === tab ? 'var(--accent)' : 'var(--t3)',
                  borderBottom: activeTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                  marginBottom: '-1px',
                  fontWeight: activeTab === tab ? 600 : 400,
                  transition: 'color 0.15s, border-color 0.15s',
                  position: 'relative',
                }}
              >
                {t(TAB_LABELS[tab] as any)}
                {tab === 'spec' && hasSpec && (
                  <span style={{
                    display: 'inline-block', width: 7, height: 7,
                    borderRadius: '50%', background: 'var(--green)',
                    marginLeft: 6, verticalAlign: 'middle',
                  }} />
                )}
                {tab === 'plan' && planContent && (
                  <span style={{
                    display: 'inline-block', width: 7, height: 7,
                    borderRadius: '50%', background: 'var(--green)',
                    marginLeft: 6, verticalAlign: 'middle',
                  }} />
                )}
                {/* file badge */}
                {tab === 'spec' && (
                  <span className="file-badge" style={{ marginLeft: 6 }}>spec.md</span>
                )}
                {tab === 'plan' && (
                  <span className="file-badge" style={{ marginLeft: 6 }}>plan.md</span>
                )}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="plan-tab-content">
            {getTabContent()}
          </div>
        </div>
      }
      actions={
        <>
          <button className="btn btn-primary" onClick={handleLockPlan} disabled={lockDisabled}>
            {t('plan.lock')}
          </button>
          <button className="btn btn-ghost" onClick={handleRegenerate} disabled={regenerateDisabled}>
            {t('plan.regenerate')}
          </button>
        </>
      }
      chatTitle={useSpecChat ? t('spec.chat_title') : t('plan.chat_title')}
      chatMessages={useSpecChat ? spec.specMessages : messages}
      chatOnSend={useSpecChat ? spec.sendSpecMessage : sendMessage}
      chatResponding={useSpecChat ? spec.specResponding : responding}
      chatCancelling={useSpecChat ? spec.specCancelling : cancelling}
      chatOnStop={useSpecChat ? spec.stopSpecGeneration : stopGeneration}
      isStale={useSpecChat ? spec.isStale : isStale}
      onRetry={useSpecChat ? spec.refreshSpecSession : refreshSession}
    />
  )
}

function EmptyArtifact({ label }: { label: string }) {
  const { t } = useLocale()
  return (
    <div style={{ color: 'var(--t3)', textAlign: 'center', padding: '40px', fontSize: '13px' }}>
      {label} — {t('artifact.not_generated')}
    </div>
  )
}
