import { useState, useEffect, useCallback, useMemo } from 'react'
import { getTask, TaskData } from '../api'
import { SessionStatus } from '../types/enums'
import { sessionIds } from '../utils/sessionIds'
import { useAgent } from './useAgent'
import type { WSEvent } from '../ws'

// Only subscribe to the spec session when the task is in PLANNING state (status=2).
// For tasks in other states, the spec panel is readonly and polling is not needed.
const PLANNING_STATUS = 2

export function useSpecStage(taskId: string | undefined, task?: TaskData | null) {
  const [initialSpec, setInitialSpec] = useState('')
  const [chatSpecContent, setChatSpecContent] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)

  const refreshTask = useCallback(() => {
    if (taskId) {
      getTask(taskId).then(t => {
        setInitialSpec(t.spec_doc || '')
      }).catch(() => {/* ignore — main task load in usePlanStage handles error */})
    }
  }, [taskId])

  useEffect(() => { refreshTask() }, [refreshTask])

  // Subscribe to the spec session whenever the task is in PLANNING state.
  // Spec is now always auto-generated on confirm-init, so no activation guard needed.
  const isPlanning = task?.status === PLANNING_STATUS
  const sessionId = (taskId && isPlanning) ? sessionIds.spec(taskId) : null

  const onUpdated = useCallback((event: WSEvent) => {
    if (event.type === 'spec_updated' && event.content) {
      setChatSpecContent(event.content)
    }
  }, [])

  const agent = useAgent({
    sessionId,
    stage: 'spec',
    entityId: taskId || '',
    onUpdated,
  })

  useEffect(() => {
    if (agent.status === SessionStatus.DONE || agent.status === SessionStatus.FAILED) {
      setGenerating(false)
      refreshTask()
    }
  }, [agent.status, refreshTask])

  // Derive spec content: WS live > log-derived > DB value
  const logDerivedSpec = useMemo(() => {
    for (let i = agent.logs.length - 1; i >= 0; i--) {
      if (agent.logs[i].type === 'spec_updated' && agent.logs[i].content) {
        return agent.logs[i].content!
      }
    }
    return ''
  }, [agent.logs])

  const specContent = chatSpecContent ?? (logDerivedSpec || initialSpec)

  const refreshSession = useCallback(() => {
    setChatSpecContent(null)
    setGenerating(true)
    agent.refreshSession()
  }, [agent.refreshSession])

  return {
    specContent,
    specStatus: agent.status,
    specLogs: agent.logs,
    specError: agent.error,
    generating: generating || agent.status === SessionStatus.RUNNING,
    isStale: agent.isStale,
    specMessages: agent.messages,
    sendSpecMessage: agent.sendMessage,
    specResponding: agent.responding,
    specCancelling: agent.cancelling,
    stopSpecGeneration: agent.stopGeneration,
    refreshSpecSession: refreshSession,
  }
}
