import { useState, useCallback } from 'react'

interface ThinkingBlockProps {
  content: string
  timestamp?: string
}

export default function ThinkingBlock({ content, timestamp }: ThinkingBlockProps) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const preview = content.length > 80 ? content.slice(0, 80) + '...' : content

  const handleCopy = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }).catch(() => {})
  }, [content])

  return (
    <div className="log-collapsible thinking-block">
      <div className="log-collapsible-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="log-label log-label-thinking">
          {open ? 'Thinking' : `Thinking: ${preview}`}
        </span>
        <span className="thinking-actions">
          {timestamp && <span className="thinking-time">{timestamp}</span>}
          {open && (
            <button className="thinking-copy-btn" onClick={handleCopy}>
              {copied ? '✓' : '⎘'}
            </button>
          )}
        </span>
      </div>
      {open && (
        <div className="log-collapsible-body thinking-body">
          {content}
        </div>
      )}
    </div>
  )
}
