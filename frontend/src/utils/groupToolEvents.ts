/**
 * Shared utility for grouping consecutive tool_call/tool_result/thinking events
 * into collapsible tool-group blocks.
 *
 * Used by both ChatPanel (chat messages) and ProjectInit (session logs).
 */

export type ToolEntry = { toolName: string; args?: Record<string, unknown>; result?: string }

/**
 * Flush pending tool state into groups.
 * Core logic shared between groupChatToolEvents and groupLogBlocks.
 */
function processTool(
  event: { type: string; tool_name?: string; args?: Record<string, unknown>; content?: string },
  pendingTool: { toolName: string; args?: Record<string, unknown> } | null,
  toolGroup: ToolEntry[],
): { pendingTool: typeof pendingTool } {
  if (event.type === 'tool_call') {
    if (pendingTool) {
      toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args })
    }
    return { pendingTool: { toolName: event.tool_name ?? '?', args: event.args } }
  }
  if (event.type === 'tool_result') {
    const raw = event.content ?? ''
    const resultContent = typeof raw === 'string' ? raw : String(raw)
    if (pendingTool) {
      toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args, result: resultContent })
    } else {
      toolGroup.push({ toolName: event.tool_name ?? '?', result: resultContent })
    }
    return { pendingTool: null }
  }
  return { pendingTool }
}

export type ChatEventBlock =
  | { kind: 'tool-group'; tools: ToolEntry[] }
  | { kind: 'thinking'; content: string }

/**
 * Group chat message events (thinking/tool_call/tool_result) into blocks.
 * Used by ChatPanel for individual AI messages.
 */
export function groupChatToolEvents(events: Array<{ type: string; tool_name?: string; args?: Record<string, unknown>; content?: string }>): ChatEventBlock[] {
  if (!events || events.length === 0) return []
  const blocks: ChatEventBlock[] = []
  let toolGroup: ToolEntry[] = []
  let pendingTool: { toolName: string; args?: Record<string, unknown> } | null = null
  let thinkingBuf = ''

  const flushThinking = () => {
    if (thinkingBuf) {
      blocks.push({ kind: 'thinking', content: thinkingBuf })
      thinkingBuf = ''
    }
  }

  const flushToolGroup = () => {
    if (pendingTool) {
      toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args })
      pendingTool = null
    }
    if (toolGroup.length > 0) {
      blocks.push({ kind: 'tool-group', tools: [...toolGroup] })
      toolGroup = []
    }
  }

  for (const ev of events) {
    if (ev.type === 'thinking') {
      flushToolGroup()
      thinkingBuf += ev.content || ''
    } else if (ev.type === 'tool_call' || ev.type === 'tool_result') {
      flushThinking()
      const result = processTool(ev, pendingTool, toolGroup)
      pendingTool = result.pendingTool
    }
  }
  flushThinking()
  flushToolGroup()
  return blocks
}

export type LogBlock =
  | { kind: 'text'; content: string }
  | { kind: 'tool-group'; tools: ToolEntry[] }
  | { kind: 'thinking'; content: string }
  | { kind: 'skill'; name: string }
  | { kind: 'error'; content: string }
  | { kind: 'status'; status: number }

/**
 * Group session log events into display blocks (text, tool-groups, thinking, errors, status).
 * Used by ProjectInit for session log modals.
 */
export function groupLogBlocks(logs: Array<{ type: string; content?: string; tool_name?: string; args?: Record<string, unknown>; error?: string; status?: number }>): LogBlock[] {
  const blocks: LogBlock[] = []
  let textBuf = ''
  let toolGroup: ToolEntry[] = []
  let pendingTool: { toolName: string; args?: Record<string, unknown> } | null = null
  let thinkingBuf = ''

  const flushText = () => {
    if (textBuf) { blocks.push({ kind: 'text', content: textBuf }); textBuf = '' }
  }
  const flushThinking = () => {
    if (thinkingBuf) { blocks.push({ kind: 'thinking', content: thinkingBuf }); thinkingBuf = '' }
  }
  const flushToolGroup = () => {
    if (pendingTool) {
      toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args })
      pendingTool = null
    }
    if (toolGroup.length > 0) {
      blocks.push({ kind: 'tool-group', tools: [...toolGroup] })
      toolGroup = []
    }
  }

  for (const log of logs) {
    if (log.type === 'text_delta') {
      flushThinking(); flushToolGroup()
      const c = log.content ?? ''
      textBuf += typeof c === 'string' ? c : String(c)
    } else if (log.type === 'thinking') {
      flushText(); flushToolGroup()
      thinkingBuf += log.content ?? ''
    } else if (log.type === 'tool_call' || log.type === 'tool_result') {
      flushText(); flushThinking()
      const result = processTool(log, pendingTool, toolGroup)
      pendingTool = result.pendingTool
    } else if (log.type === 'skill_loaded') {
      flushText(); flushToolGroup()
      const name = (log as any).skill_name || ''
      if (name) blocks.push({ kind: 'skill', name })
    } else if (log.type === 'error') {
      flushText(); flushThinking(); flushToolGroup()
      const errContent = log.content ?? log.error ?? ''
      blocks.push({ kind: 'error', content: typeof errContent === 'string' ? errContent : String(errContent) })
    } else if (log.type === 'status_change') {
      flushText(); flushThinking(); flushToolGroup()
      blocks.push({ kind: 'status', status: log.status ?? 0 })
    }
  }
  flushText(); flushThinking(); flushToolGroup()
  return blocks
}
