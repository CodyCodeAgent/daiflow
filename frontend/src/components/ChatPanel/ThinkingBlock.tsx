import { useState } from 'react'

export default function ThinkingBlock({ content }: { content: string }) {
  const [open, setOpen] = useState(false)
  const preview = content.length > 80 ? content.slice(0, 80) + '...' : content

  return (
    <div className="log-collapsible thinking-block">
      <div className="log-collapsible-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="log-label log-label-thinking">
          {open ? 'Thinking' : `Thinking: ${preview}`}
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
