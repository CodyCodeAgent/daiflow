import { useState, useCallback, useRef, useEffect } from 'react'
import { getSessionLogs } from '../api'
import { wsClient, WSEvent } from '../ws'
import type { SessionEvent } from './useSession'

/** Generate unique message IDs using crypto.randomUUID when available, with fallback. */
const nextMsgId = typeof crypto !== 'undefined' && crypto.randomUUID
  ? () => `msg_${crypto.randomUUID()}`
  : (() => { let c = 0; return () => `msg_${++c}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}` })()

/** A tool-call or tool-result event attached to an AI message. */
interface ChatToolEvent {
  type: string
  tool_name?: string
  args?: Record<string, unknown>
  tool_call_id?: string
  content?: string
  skill_name?: string
}

export interface ToolReview {
  callId: string
  toolName: string
  args?: Record<string, unknown>
  content?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'ai'
  content: string
  events?: ChatToolEvent[]
  done?: boolean
  pendingReviews?: ToolReview[]
}

interface UseStageChatOptions {
  sessionId: string | null
  /** Chat stage — must match backend stage names */
  stage: 'spec' | 'plan' | 'todo' | 'todo_exec' | 'review' | 'conversation'
  /** Entity ID: task_id for plan/todo/review, todo_id for todo_exec */
  entityId: string
  onUpdated?: (event: WSEvent) => void
  /** Real-time session logs from useSession — used to show initial generation progress */
  sessionLogs?: SessionEvent[]
}

interface LogEvent {
  type?: string
  event_type?: string
  content?: string
  tool_name?: string
  args?: Record<string, unknown>
  tool_call_id?: string
}

function rebuildMessages(logs: LogEvent[]): ChatMessage[] {
  const messages: ChatMessage[] = []
  let currentAI: ChatMessage | null = null

  for (const event of logs) {
    if (event.type === 'user_message') {
      if (currentAI) {
        messages.push(currentAI)
        currentAI = null
      }
      messages.push({ id: nextMsgId(), role: 'user', content: event.content || '' })
    } else if (event.type === 'text_delta') {
      if (!currentAI) {
        currentAI = { id: nextMsgId(), role: 'ai', content: '', events: [] }
      }
      currentAI.content += event.content || ''
    } else if (event.type === 'thinking' || event.type === 'tool_call' || event.type === 'tool_result' || event.type === 'skill_loaded') {
      if (!currentAI) {
        currentAI = { id: nextMsgId(), role: 'ai', content: '', events: [] }
      }
      currentAI.events = currentAI.events || []
      currentAI.events.push(event as ChatToolEvent)
    } else if (event.type === 'done' || event.type === 'status_change') {
      if (currentAI) {
        currentAI.done = true
        messages.push(currentAI)
        currentAI = null
      }
    }
  }
  if (currentAI) messages.push(currentAI)
  return messages
}

export function useStageChat({ sessionId, stage, entityId, onUpdated, sessionLogs }: UseStageChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [userHasChatted, setUserHasChatted] = useState(false)
  const cancelRef = useRef<(() => void) | null>(null)
  const reqIdRef = useRef<string | null>(null)
  // Ref to avoid stale closure: onUpdated may change while streaming is active
  const onUpdatedRef = useRef(onUpdated)
  onUpdatedRef.current = onUpdated

  // Refs for rAF-throttled streaming updates
  const aiContentRef = useRef('')
  const aiEventsRef = useRef<ChatToolEvent[]>([])
  const aiIdRef = useRef('')
  const aiReviewsRef = useRef<ToolReview[]>([])
  const rafRef = useRef<number | null>(null)

  const flushAIMessage = useCallback(() => {
    rafRef.current = null
    const id = aiIdRef.current
    const content = aiContentRef.current
    const events = aiEventsRef.current
    const reviews = aiReviewsRef.current
    setMessages(prev => [
      ...prev.slice(0, -1),
      { id, role: 'ai' as const, content, events: [...events], pendingReviews: reviews.length > 0 ? [...reviews] : undefined },
    ])
  }, [])

  const scheduleFlush = useCallback(() => {
    if (rafRef.current === null) {
      rafRef.current = requestAnimationFrame(flushAIMessage)
    }
  }, [flushAIMessage])

  // Load history from logs on mount
  useEffect(() => {
    if (!sessionId) return
    getSessionLogs(sessionId)
      .then(logs => {
        if (Array.isArray(logs) && logs.length > 0) {
          setMessages(rebuildMessages(logs))
        }
      })
      .catch(err => console.error('Failed to load chat logs:', err))
  }, [sessionId])

  // Rebuild messages from real-time session logs during initial generation
  useEffect(() => {
    if (!userHasChatted && sessionLogs && sessionLogs.length > 0) {
      setMessages(rebuildMessages(sessionLogs))
    }
  }, [sessionLogs, userHasChatted])

  const sendMessage = useCallback((text: string, opts?: { contextFiles?: string[]; images?: string[] }) => {
    if (!text.trim() || streaming || !stage || !entityId) return

    // Cancel any previous stream
    cancelRef.current?.()

    setUserHasChatted(true)

    // Add user message
    const userMsg: ChatMessage = { id: nextMsgId(), role: 'user', content: text }
    const aiId = nextMsgId()
    aiContentRef.current = ''
    aiEventsRef.current = []
    aiReviewsRef.current = []
    aiIdRef.current = aiId

    setMessages(prev => [
      ...prev,
      userMsg,
      { id: aiId, role: 'ai', content: '', events: [] },
    ])
    setStreaming(true)

    const { cancel, reqId } = wsClient.sendChat(stage, entityId, text, (event: WSEvent) => {
      if (event.type === 'text_delta') {
        aiContentRef.current += event.content || ''
        scheduleFlush()
      } else if (event.type === 'thinking' || event.type === 'tool_call' || event.type === 'tool_result' || event.type === 'skill_loaded') {
        aiEventsRef.current = [...aiEventsRef.current, event]
        scheduleFlush()
      } else if (event.type === 'tool_review') {
        aiReviewsRef.current = [...aiReviewsRef.current, {
          callId: event.call_id || '',
          toolName: event.tool_name || '',
          args: event.args,
          content: event.content,
        }]
        scheduleFlush()
      } else if (event.type === 'tool_reverted') {
        aiReviewsRef.current = aiReviewsRef.current.filter(r => r.callId !== event.call_id)
        scheduleFlush()
      } else if (event.type === 'plan_updated' || event.type === 'todo_updated' || event.type === 'code_updated') {
        onUpdatedRef.current?.(event)
      } else if (event.type === 'error') {
        aiContentRef.current += `\n\n[Error: ${event.content || 'Unknown error'}]`
        // Treat error as terminal — stop streaming and finalize message
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current)
          rafRef.current = null
        }
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'ai') {
            return [...prev.slice(0, -1), { ...last, content: aiContentRef.current, events: [...aiEventsRef.current], done: true }]
          }
          return prev
        })
        setStreaming(false)
        setCancelling(false)
        cancelRef.current = null
        reqIdRef.current = null
        return
      } else if (event.type === 'done') {
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current)
          rafRef.current = null
        }
        // Mark message as done before final flush
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'ai') {
            return [...prev.slice(0, -1), { ...last, content: aiContentRef.current, events: [...aiEventsRef.current], done: true }]
          }
          return prev
        })
        setStreaming(false)
        setCancelling(false)
        cancelRef.current = null
        reqIdRef.current = null
      }
    }, { contextFiles: opts?.contextFiles, images: opts?.images })
    cancelRef.current = cancel
    reqIdRef.current = reqId
  }, [stage, entityId, streaming, scheduleFlush, flushAIMessage])

  const stopGeneration = useCallback(() => {
    if (!streaming || cancelling) return
    if (reqIdRef.current) {
      setCancelling(true)
      wsClient.cancelChat(reqIdRef.current)
    }
  }, [streaming, cancelling])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cancelRef.current?.()
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
      }
    }
  }, [])

  return { messages, sendMessage, streaming, cancelling, stopGeneration }
}
