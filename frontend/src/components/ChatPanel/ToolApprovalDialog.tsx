import { wsClient } from '../../ws'
import './ToolApprovalDialog.css'

interface ToolApprovalDialogProps {
  callId: string
  toolName: string
  args?: Record<string, unknown>
  content?: string
  onResolved: () => void
}

export default function ToolApprovalDialog({ callId, toolName, args, content, onResolved }: ToolApprovalDialogProps) {
  const filePath = args?.path ?? args?.file_path ?? ''

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
      {content && (
        <pre className="tool-approval-content">{
          content.length > 2000 ? content.slice(0, 2000) + '\n...' : content
        }</pre>
      )}
      {args && !filePath && (
        <pre className="tool-approval-content">{JSON.stringify(args, null, 2)}</pre>
      )}
      <div className="tool-approval-actions">
        <button className="btn btn-sm btn-ghost" onClick={handleAccept}>Keep</button>
        <button className="btn btn-sm btn-danger" onClick={handleRevert}>Revert</button>
      </div>
    </div>
  )
}
