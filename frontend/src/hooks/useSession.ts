import { useState, useEffect, useCallback, useRef } from 'react'
import { getSessionStatus, getSessionLogs } from '../api'
import { SessionStatus } from '../types/enums'
import { useWsSync } from './useWsSync'

export interface SessionEvent {
  type: string
  content?: string
  tool_name?: string
  args?: Record<string, unknown>
  tool_call_id?: string
  status?: number
  error?: string
  ts?: string
  session_id?: string
  started_at?: string
  finished_at?: string
  skill_name?: string
  usage?: { input_tokens: number; output_tokens: number }
}

// Convert API log response to SessionEvent
function convertLogToEvent(log: Record<string, unknown>): SessionEvent {
  return {
    type: (log.event_type as string) || (log.type as string) || 'unknown',
    content: log.content as string | undefined,
    tool_name: log.tool_name as string | undefined,
    args: log.args as Record<string, unknown> | undefined,
    tool_call_id: log.tool_call_id as string | undefined,
    status: log.status as number | undefined,
    error: log.error as string | undefined,
    ts: log.ts as string | undefined,
    session_id: log.session_id as string | undefined,
    skill_name: log.skill_name as string | undefined,
  }
}

function isTerminal(status: number): boolean {
  return status === SessionStatus.DONE || status === SessionStatus.FAILED
}

function isSessionNotReadyError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err || '')
  return msg.includes('API error: 404') || msg.includes('Session not found')
}

export function useSession(sessionId: string | null, refreshKey?: number) {
  const [status, setStatus] = useState<number>(0)
  const [logs, setLogs] = useState<SessionEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  // Use ref to accumulate logs and rAF to batch updates
  const logsRef = useRef<SessionEvent[]>([])
  const rafRef = useRef<number | null>(null)
  const mountedRef = useRef(true)

  const flushLogs = useCallback(() => {
    rafRef.current = null
    if (mountedRef.current) {
      setLogs([...logsRef.current])
    }
  }, [])

  // Cleanup rAF on unmount
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [])

  useWsSync({
    channel: sessionId ? `session:${sessionId}` : null,
    refreshKey,
    onReset: () => {
      logsRef.current = []
      setLogs([])
      setStatus(0)
      setError(null)
    },
    onEvent: (event) => {
      logsRef.current.push(event)
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(flushLogs)
      }
      if (event.type === 'status_change') {
        if (event.status != null) setStatus(event.status)
        if (event.error) setError(event.error)
        return event.status != null && isTerminal(event.status)
      }
    },
    fetchData: async () => {
      try {
        const statusData = await getSessionStatus(sessionId!)
        setStatus(statusData.status)

        const logsData = await getSessionLogs(sessionId!)
        if (Array.isArray(logsData)) {
          const events = logsData.map(convertLogToEvent)
          logsRef.current = events
          setLogs(events)
        }

        return isTerminal(statusData.status)
      } catch (err: any) {
        // todo_exec session rows are created asynchronously after execute starts.
        // Treat transient 404 as "not ready yet" rather than a hard UI error.
        if (!isSessionNotReadyError(err)) {
          setError(err.message)
        }
        return false
      }
    },
    pollCheck: async () => {
      // Lightweight: only check status, don't re-fetch logs (WS provides them in real-time)
      let s
      try {
        s = await getSessionStatus(sessionId!)
      } catch (err) {
        if (isSessionNotReadyError(err)) {
          return false
        }
        throw err
      }
      setStatus(s.status)
      if (isTerminal(s.status)) {
        // Fetch logs one final time to get complete state
        const finalLogs = await getSessionLogs(sessionId!)
        if (Array.isArray(finalLogs)) {
          const events = finalLogs.map(convertLogToEvent)
          logsRef.current = events
          setLogs(events)
        }
        return true
      }
      return false
    },
  })

  return { status, logs, error }
}
