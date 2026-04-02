import { useState, useRef, useEffect, useCallback } from 'react'
import { useLocale } from '../../hooks/useLocale'
import type { ChatMessage } from '../../hooks/useStageChat'
import MarkdownViewer from '../MarkdownViewer/MarkdownViewer'
import ToolGroupBlock from '../ToolGroupBlock/ToolGroupBlock'
import ThinkingBlock from './ThinkingBlock'
import ToolApprovalDialog from './ToolApprovalDialog'
import ChatInput from './ChatInput'
import { groupChatToolEvents } from '../../utils/groupToolEvents'

/** Distance (px) from bottom to consider "near bottom" for auto-scroll. */
const SCROLL_NEAR_BOTTOM_PX = 80

/** Max visible lines before a user message is collapsed. */
const USER_MSG_COLLAPSE_LINES = 3

function CollapsibleMsg({ content }: { content: string }) {
  const { t } = useLocale()
  const lines = content.split('\n')
  const shouldCollapse = lines.length > USER_MSG_COLLAPSE_LINES
  const [collapsed, setCollapsed] = useState(shouldCollapse)

  return (
    <div className="collapsible-msg">
      <div className={`collapsible-msg-body ${collapsed ? 'clamped' : ''}`}>
        <MarkdownViewer content={content} />
      </div>
      {shouldCollapse && (
        <button
          className="msg-toggle-btn"
          onClick={() => setCollapsed(c => !c)}
        >
          {collapsed ? t('chat.expand') : t('chat.collapse')}
        </button>
      )}
    </div>
  )
}

export interface ChatSendOptions {
  contextFiles?: string[]
  images?: string[]
}

interface ChatPanelProps {
  messages: ChatMessage[]
  onSend: (text: string, opts?: ChatSendOptions) => void
  /** True when AI is actively generating: initial session running or user chat streaming. */
  responding?: boolean
  /** True when a cancel request has been sent but not yet confirmed. */
  cancelling?: boolean
  /** Called when user clicks the stop button during streaming. */
  onStop?: () => void
  title?: string
  disabled?: boolean
  style?: React.CSSProperties
  /** Task ID for @ file mention autocomplete */
  taskId?: string
}

export default function ChatPanel({
  messages, onSend, responding = false, cancelling = false, onStop,
  title, disabled = false, style, taskId,
}: ChatPanelProps) {
  const { t } = useLocale()
  const messagesRef = useRef<HTMLDivElement>(null)

  const isNearBottomRef = useRef(true)

  const handleScroll = () => {
    if (!messagesRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = messagesRef.current
    isNearBottomRef.current = scrollHeight - scrollTop - clientHeight < SCROLL_NEAR_BOTTOM_PX
  }

  useEffect(() => {
    if (messagesRef.current && isNearBottomRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [messages])

  const handleSend = useCallback((text: string, opts?: ChatSendOptions) => {
    if (disabled || responding) return
    onSend(text, opts)
  }, [disabled, responding, onSend])

  return (
    <div className="chat-panel" style={style}>
      <div className="chat-header">
        <div className="dot-live" />
        {title || t('chat.default_title')}
      </div>
      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {messages.map((msg, i) => {
          const toolGroups = msg.role === 'ai' ? groupChatToolEvents(msg.events || []) : []
          const loadedSkills = msg.role === 'ai'
            ? (msg.events || []).filter(e => e.type === 'skill_loaded').map(e => (e as any).skill_name || '').filter(Boolean)
            : []
          const isLastAi = msg.role === 'ai' && i === messages.length - 1
          const isAiStreaming = isLastAi && responding
          const isAiDone = msg.role === 'ai' && msg.done === true

          return (
            <div key={msg.id} className={`msg ${msg.role === 'user' ? 'user' : ''}`}>
              <div className={msg.role === 'ai' ? 'avatar avatar-ai' : 'avatar avatar-u'}>
                {msg.role === 'ai' ? 'AI' : 'U'}
              </div>
              <div className="bubble">
                {msg.content && (
                  msg.role === 'user'
                    ? <CollapsibleMsg content={msg.content} />
                    : <MarkdownViewer content={msg.content} />
                )}
                {loadedSkills.length > 0 && (
                  <div className="chat-skills">
                    {loadedSkills.map((name, j) => (
                      <span key={j} className="skill-tag">📄 {name}</span>
                    ))}
                  </div>
                )}
                {toolGroups.length > 0 && (
                  <div className="chat-tool-groups">
                    {toolGroups.map((block, j) =>
                      block.kind === 'tool-group'
                        ? <ToolGroupBlock key={j} tools={block.tools} />
                        : <ThinkingBlock key={j} content={block.content} />
                    )}
                  </div>
                )}
                {msg.pendingReviews && msg.pendingReviews.length > 0 && (
                  <div className="chat-reviews">
                    {msg.pendingReviews.map(review => (
                      <ToolApprovalDialog
                        key={review.callId}
                        callId={review.callId}
                        toolName={review.toolName}
                        args={review.args}
                        content={review.content}
                        onResolved={() => {}}
                      />
                    ))}
                  </div>
                )}
                {msg.role === 'ai' && (
                  <div className="msg-status">
                    {isAiStreaming ? (
                      <span className="msg-status-spinner" title="AI responding..." />
                    ) : isAiDone && msg.content ? (
                      <svg className="msg-status-check" width="14" height="14" viewBox="0 0 14 14" fill="none">
                        <path d="M3 7L6 10L11 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <ChatInput
        onSend={handleSend}
        disabled={disabled}
        taskId={taskId}
        placeholder={disabled ? '' : t('chat.placeholder')}
        responding={responding}
        cancelling={cancelling}
        onStop={onStop}
      />
    </div>
  )
}
