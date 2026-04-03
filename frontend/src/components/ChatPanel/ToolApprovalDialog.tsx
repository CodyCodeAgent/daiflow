import { useMemo } from 'react'
import { wsClient } from '../../ws'
import { useLocale } from '../../hooks/useLocale'
import './ToolApprovalDialog.css'

interface ToolApprovalDialogProps {
  callId: string
  toolName: string
  args?: Record<string, unknown>
  content?: string
  onResolved: () => void
}

/** Simple inline diff: highlight added/removed lines with color. */
function InlineDiff({ content }: { content: string }) {
  const lines = content.split('\n')
  return (
    <pre className="tool-approval-content tool-approval-diff">
      {lines.map((line, i) => {
        let cls = ''
        if (line.startsWith('+')) cls = 'diff-add'
        else if (line.startsWith('-')) cls = 'diff-rm'
        else if (line.startsWith('@@')) cls = 'diff-hunk'
        return <div key={i} className={cls}>{line}</div>
      })}
    </pre>
  )
}

export default function ToolApprovalDialog({ callId, toolName, args, content, onResolved }: ToolApprovalDialogProps) {
  const { t } = useLocale()
  const filePath = args?.path ?? args?.file_path ?? ''

  // Detect if content looks like a diff (has +/- lines)
  const isDiff = useMemo(() => {
    if (!content) return false
    const lines = content.split('\n').slice(0, 20)
    return lines.some(l => l.startsWith('@@') || l.startsWith('+++') || l.startsWith('---'))
  }, [content])

  const displayContent = content && content.length > 3000
    ? content.slice(0, 3000) + '\n...'
    : content

  const handleAccept = () => {
    wsClient.sendToolResponse(callId, 'accept')
    onResolved()
  }

  const handleRevert = () => {
    wsClient.sendToolResponse(callId, 'revert')
    onResolved()
  }

  return (
    <div className="tool-approval">
      <div className="tool-approval-header">
        <span className="tool-approval-icon">&#9888;</span>
        <span className="tool-approval-title">Tool Review: {toolName}</span>
      </div>
      {filePath && <div className="tool-approval-path"><code>{String(filePath)}</code></div>}
      {displayContent && (
        isDiff ? <InlineDiff content={displayContent} /> : (
          <pre className="tool-approval-content">{displayContent}</pre>
        )
      )}
      {args && !filePath && !content && (
        <pre className="tool-approval-content">{JSON.stringify(args, null, 2)}</pre>
      )}
      <div className="tool-approval-actions">
        <button className="btn btn-sm btn-ghost" onClick={handleAccept}>{t('tool_approval.accept')}</button>
        <button className="btn btn-sm btn-danger" onClick={handleRevert}>{t('tool_approval.revert')}</button>
      </div>
    </div>
  )
}
