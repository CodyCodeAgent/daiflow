import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import StageLayout, { isStageReadonly } from '../../../components/StageLayout/StageLayout'
import MarkdownViewer from '../../../components/MarkdownViewer/MarkdownViewer'
import { usePlanStage } from '../../../hooks/usePlanStage'
import { lockPlan, triggerPlan, getTaskArtifact, type ArtifactResponse } from '../../../api'
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
  const { task, planContent, status, messages, sendMessage, responding, cancelling, stopGeneration, regenerating, refreshSession, isStale, spec, specGenerating, specDone } = usePlanStage(taskId)

  const readonly = task ? isStageReadonly(task.status, 2) : false
  const [activeTab, setActiveTab] = useState<ArtifactTab>('plan')
  const [researchArtifact, setResearchArtifact] = useState<ArtifactResponse | null>(null)
  const [dataModelArtifact, setDataModelArtifact] = useState<ArtifactResponse | null>(null)
  const [loadingArtifacts, setLoadingArtifacts] = useState(false)

  const hasSpec = !!spec.specContent

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

  const isGenerating = responding || regenerating
  const lockDisabled = !planContent || isGenerating || readonly
  const regenerateDisabled = isGenerating || readonly

  // Determine which tabs to show (spec is a background step, not shown as a tab)
  const visibleTabs: ArtifactTab[] = ['plan']
  if (researchArtifact?.exists) visibleTabs.push('research')
  if (dataModelArtifact?.exists) visibleTabs.push('data-model')

  // Phase-based loading: show full-page phase indicator when no plan content yet
  if (!planContent && !readonly) {
    if (specGenerating) {
      return (
        <StageLayout
          taskId={taskId!}
          task={task}
          currentStage={2}
          content={
            <div className="card plan-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '240px' }}>
              <div className="typing-row" style={{ justifyContent: 'center' }}>
                <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
              </div>
              <div style={{ marginTop: 12, fontSize: '14px', color: 'var(--t2)' }}>{t('plan.phase_spec')}</div>
            </div>
          }
          actions={<></>}
          chatTitle={t('plan.chat_title')}
          chatMessages={messages}
          chatOnSend={sendMessage}
          chatResponding={responding}
          chatCancelling={cancelling}
          chatOnStop={stopGeneration}
          isStale={isStale}
          onRetry={refreshSession}
        />
      )
    }
    if (specDone && status === 1) {
      return (
        <StageLayout
          taskId={taskId!}
          task={task}
          currentStage={2}
          content={
            <div className="card plan-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '240px' }}>
              <div className="typing-row" style={{ justifyContent: 'center' }}>
                <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
              </div>
              <div style={{ marginTop: 12, fontSize: '14px', color: 'var(--t2)' }}>{t('plan.phase_plan')}</div>
            </div>
          }
          actions={<></>}
          chatTitle={t('plan.chat_title')}
          chatMessages={messages}
          chatOnSend={sendMessage}
          chatResponding={responding}
          chatCancelling={cancelling}
          chatOnStop={stopGeneration}
          isStale={isStale}
          onRetry={refreshSession}
        />
      )
    }
  }

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
      return <MarkdownViewer content={spec.specContent} />
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
        <p style={{ fontSize: '13px', color: 'var(--t3)' }}>{t('spec.generating')}</p>
      </div>
    )
  }

  const renderPlanTab = () => {
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
          <span className="btn-with-tooltip">
            <button className="btn btn-primary" onClick={handleLockPlan} disabled={lockDisabled}>
              {t('plan.lock')}
            </button>
            {lockDisabled && !readonly && (
              <span className="btn-tooltip">
                {isGenerating ? t('tooltip.generating') : !planContent ? t('tooltip.need_plan') : ''}
              </span>
            )}
            {readonly && <span className="btn-tooltip">{t('tooltip.readonly')}</span>}
          </span>
          <span className="btn-with-tooltip">
            <button className="btn btn-ghost" onClick={handleRegenerate} disabled={regenerateDisabled}>
              {t('plan.regenerate')}
            </button>
            {readonly && <span className="btn-tooltip">{t('tooltip.readonly')}</span>}
          </span>
        </>
      }
      chatTitle={t('plan.chat_title')}
      chatMessages={messages}
      chatOnSend={sendMessage}
      chatResponding={responding}
      chatCancelling={cancelling}
      chatOnStop={stopGeneration}
      isStale={isStale}
      onRetry={refreshSession}
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
