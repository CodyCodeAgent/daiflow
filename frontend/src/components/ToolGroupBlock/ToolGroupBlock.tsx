import { useState } from 'react'
import type { ToolEntry } from '../../utils/groupToolEvents'
import ToolItemRenderer from './ToolItemRenderer'
import './ToolGroupBlock.css'

export default function ToolGroupBlock({ tools }: { tools: ToolEntry[] }) {
  const [open, setOpen] = useState(false)

  const names = [...new Set(tools.map(t => t.toolName).filter(Boolean))]
  const summary = `${tools.length} tool calls` + (names.length > 0 ? ` — ${names.join(', ')}` : '')

  return (
    <div className="log-collapsible">
      <div className="log-collapsible-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="log-label log-label-tool">{summary}</span>
      </div>
      {open && (
        <div className="log-collapsible-body log-tool-group-body">
          {tools.map((t, i) => (
            <ToolItemRenderer key={i} tool={t} />
          ))}
        </div>
      )}
    </div>
  )
}
