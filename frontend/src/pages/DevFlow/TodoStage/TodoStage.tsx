import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import StageLayout, { isStageReadonly } from '../../../components/StageLayout/StageLayout'
import { useTodoStage } from '../../../hooks/useTodoStage'
import { startCoding, triggerTodo } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import { useToast } from '../../../components/Toast/ToastContext'
import type { TodoData } from '../../../api'
import './TodoStage.css'

/** Extract type badge (Frontend/Backend/Full-Stack) from todo description. */
function extractTodoType(description: string): string | null {
  const m = description.match(/\*?\*?Type\*?\*?\s*[:：]\s*(\S+)/i)
  return m ? m[1].replace(/\*+/g, '') : null
}

/** Extract priority (P1/P2/P3) from todo description. */
function extractPriority(description: string): string | null {
  const m = description.match(/\*?\*?Priority\*?\*?\s*[:：]\s*(P[123])/i)
  return m ? m[1].toUpperCase() : null
}

const TYPE_COLOR: Record<string, string> = {
  frontend: 'var(--accent)',
  backend: '#8b5cf6',
  fullstack: '#0ea5e9',
  'full-stack': '#0ea5e9',
  infra: '#f59e0b',
}

const PRIORITY_COLOR: Record<string, string> = {
  P1: '#ef4444',
  P2: '#f59e0b',
  P3: '#6b7280',
}

export default function TodoStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const toast = useToast()
  const { task, todos, status, messages, sendMessage, responding, cancelling, stopGeneration, refreshSession, isStale } = useTodoStage(taskId)

  const [selectedTodo, setSelectedTodo] = useState<TodoData | null>(null)

  const handleRedecompose = async () => {
    if (!taskId) return
    await triggerTodo(taskId)
    refreshSession()
  }

  const handleStartCoding = async () => {
    if (!taskId) return
    try {
      await startCoding(taskId)
      navigate(`/devflow/${taskId}/coding`)
    } catch (err: any) {
      toast.error(err.message || t('toast.operation_failed'))
    }
  }

  const readonly = task ? isStageReadonly(task.status, 3) : false
  const isGenerating = responding
  const startCodingDisabled = todos.length === 0 || isGenerating || readonly
  const redecomposeDisabled = isGenerating || readonly

  return (
    <>
      <StageLayout
        taskId={taskId!}
        task={task}
        currentStage={3}
        content={
          <div className="card todo-wrap">
            <div className="todo-card-title">
              {t('todo.title')}
              <span className="file-badge">{t('todo.file_badge')}</span>
              {todos.length > 0 && <span className="count-badge">{todos.length}</span>}
            </div>
            {todos.length > 0 ? (
              <div className="todo-items">
                {todos.map((todo, i) => {
                  const todoType = extractTodoType(todo.description || '')
                  const priority = extractPriority(todo.description || '')
                  const typeKey = todoType?.toLowerCase() || ''
                  const typeColor = TYPE_COLOR[typeKey] || 'var(--t3)'
                  const priorityColor = PRIORITY_COLOR[priority || ''] || 'var(--t3)'

                  return (
                    <div
                      key={i}
                      className="card todo-item"
                      onClick={() => setSelectedTodo(todo)}
                    >
                      <div className="todo-seq">{String(todo.seq || i + 1).padStart(2, '0')}</div>
                      <div className="todo-title" style={{ flex: 1 }}>{todo.title}</div>
                      <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexShrink: 0 }}>
                        {todoType && (
                          <span style={{
                            fontSize: '11px',
                            padding: '2px 7px',
                            borderRadius: '4px',
                            background: typeColor + '22',
                            color: typeColor,
                            border: `1px solid ${typeColor}44`,
                            fontWeight: 500,
                          }}>
                            {todoType}
                          </span>
                        )}
                        {priority && (
                          <span style={{
                            fontSize: '11px',
                            padding: '2px 7px',
                            borderRadius: '4px',
                            background: priorityColor + '22',
                            color: priorityColor,
                            border: `1px solid ${priorityColor}44`,
                            fontWeight: 600,
                          }}>
                            {priority}
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div style={{ color: 'var(--t3)', textAlign: 'center', padding: '40px' }}>
                {status === 1 ? t('todo.decomposing') : t('todo.no_todos')}
              </div>
            )}
          </div>
        }
        actions={
          <>
            <span className="btn-with-tooltip">
              <button className="btn btn-primary" onClick={handleStartCoding} disabled={startCodingDisabled}>
                {t('todo.start_coding')}
              </button>
              {startCodingDisabled && !readonly && todos.length === 0 && (
                <span className="btn-tooltip">{t('tooltip.need_todos')}</span>
              )}
              {readonly && <span className="btn-tooltip">{t('tooltip.readonly')}</span>}
            </span>
            <span className="btn-with-tooltip">
              <button className="btn btn-ghost" onClick={handleRedecompose} disabled={redecomposeDisabled}>
                {t('todo.redecompose')}
              </button>
              {readonly && <span className="btn-tooltip">{t('tooltip.readonly')}</span>}
            </span>
          </>
        }
        chatTitle={t('todo.chat_title')}
        chatMessages={messages}
        chatOnSend={sendMessage}
        chatResponding={responding}
        chatCancelling={cancelling}
        chatOnStop={stopGeneration}
        isStale={isStale}
        onRetry={refreshSession}
      />

      {/* Todo Detail Modal */}
      {selectedTodo && (
        <>
          <div className="overlay" onClick={() => setSelectedTodo(null)} />
          <div className="todo-modal">
            <div className="todo-modal-header">
              <span className="todo-modal-seq">{String(selectedTodo.seq || '').padStart(2, '0')}</span>
              <span className="todo-modal-title">{selectedTodo.title}</span>
              <button className="todo-modal-close" onClick={() => setSelectedTodo(null)}>×</button>
            </div>
            <div className="todo-modal-body" style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: '13px', lineHeight: 1.6 }}>
              {selectedTodo.description}
            </div>
          </div>
        </>
      )}
    </>
  )
}
