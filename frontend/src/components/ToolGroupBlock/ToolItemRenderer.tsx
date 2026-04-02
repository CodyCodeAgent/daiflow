import { useState } from 'react'
import type { ToolEntry } from '../../utils/groupToolEvents'

const FILE_TOOLS = new Set(['write_file', 'edit_file', 'create_file'])
const READ_TOOLS = new Set(['read_file'])
const EXEC_TOOLS = new Set(['exec_command'])
const SEARCH_TOOLS = new Set(['grep', 'search', 'glob', 'list_dir'])

function tryParseJson(s: string): Record<string, unknown> | null {
  try { return JSON.parse(s) } catch { return null }
}

function getFilePath(args?: Record<string, unknown>): string {
  if (!args) return ''
  return String(args.path ?? args.file_path ?? '')
}

function getLanguageFromPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    ts: 'typescript', tsx: 'tsx', js: 'javascript', jsx: 'jsx',
    py: 'python', rs: 'rust', go: 'go', java: 'java',
    css: 'css', scss: 'scss', html: 'html', json: 'json',
    md: 'markdown', yaml: 'yaml', yml: 'yaml', toml: 'toml',
    sql: 'sql', sh: 'bash', bash: 'bash', zsh: 'bash',
  }
  return map[ext] || ''
}

/** File write/edit tool — shows path + summary */
function FileWriteItem({ tool }: { tool: ToolEntry }) {
  const [open, setOpen] = useState(false)
  const path = getFilePath(tool.args)
  const parsed = tool.result ? tryParseJson(tool.result) : null
  const lines = parsed?.linesCreated ?? parsed?.linesWritten ?? null
  const size = parsed?.fileSize ?? null

  return (
    <div className="tool-rich-item">
      <div className="tool-rich-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="tool-icon tool-icon-write">W</span>
        <span className="tool-rich-label">{tool.toolName}</span>
        {path && <code className="tool-file-path">{path}</code>}
        {lines != null && <span className="tool-meta">+{String(lines)} lines</span>}
        {size != null && <span className="tool-meta">{String(size)}B</span>}
      </div>
      {open && tool.args && (
        <div className="tool-rich-detail">
          {typeof tool.args.fileText === 'string' ? (
            <pre className="tool-code-block">{tool.args.fileText}</pre>
          ) : (
            <code className="log-tool-args">{JSON.stringify(tool.args, null, 2)}</code>
          )}
        </div>
      )}
    </div>
  )
}

/** File read tool — shows file content preview */
function FileReadItem({ tool }: { tool: ToolEntry }) {
  const [open, setOpen] = useState(false)
  const path = getFilePath(tool.args)
  const parsed = tool.result ? tryParseJson(tool.result) : null
  const content = parsed?.content as string | undefined
  const totalLines = parsed?.totalLines
  const lang = getLanguageFromPath(path)

  return (
    <div className="tool-rich-item">
      <div className="tool-rich-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="tool-icon tool-icon-read">R</span>
        <span className="tool-rich-label">read_file</span>
        {path && <code className="tool-file-path">{path}</code>}
        {totalLines != null && <span className="tool-meta">{String(totalLines)} lines</span>}
      </div>
      {open && content && (
        <div className="tool-rich-detail">
          <pre className={`tool-code-block${lang ? ` language-${lang}` : ''}`}>
            {content.length > 5000 ? content.slice(0, 5000) + '\n... (truncated)' : content}
          </pre>
        </div>
      )}
    </div>
  )
}

/** Shell command tool — terminal style */
function TerminalItem({ tool }: { tool: ToolEntry }) {
  const [open, setOpen] = useState(false)
  const command = tool.args?.command as string | undefined
  const parsed = tool.result ? tryParseJson(tool.result) : null
  const output = parsed?.output ?? parsed?.stdout ?? tool.result ?? ''

  return (
    <div className="tool-rich-item">
      <div className="tool-rich-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="tool-icon tool-icon-exec">$</span>
        <span className="tool-rich-label">exec_command</span>
        {command && <code className="tool-command-preview">{command.length > 60 ? command.slice(0, 60) + '...' : command}</code>}
      </div>
      {open && (
        <div className="tool-terminal-block">
          {command && <div className="tool-terminal-cmd">$ {command}</div>}
          {output && <pre className="tool-terminal-output">{String(output)}</pre>}
        </div>
      )}
    </div>
  )
}

/** Search/grep tool — shows matches */
function SearchItem({ tool }: { tool: ToolEntry }) {
  const [open, setOpen] = useState(false)
  const pattern = tool.args?.pattern ?? tool.args?.query ?? tool.args?.path ?? ''

  return (
    <div className="tool-rich-item">
      <div className="tool-rich-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="tool-icon tool-icon-search">Q</span>
        <span className="tool-rich-label">{tool.toolName}</span>
        {pattern && <code className="tool-file-path">{String(pattern)}</code>}
      </div>
      {open && tool.result && (
        <div className="tool-rich-detail">
          <pre className="tool-code-block">{tool.result.length > 3000 ? tool.result.slice(0, 3000) + '\n... (truncated)' : tool.result}</pre>
        </div>
      )}
    </div>
  )
}

/** Generic / MCP tool — card style */
function GenericItem({ tool }: { tool: ToolEntry }) {
  const [open, setOpen] = useState(false)
  const argsStr = tool.args ? JSON.stringify(tool.args, null, 2) : null

  return (
    <div className="tool-rich-item">
      <div className="tool-rich-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="tool-icon tool-icon-mcp">M</span>
        <span className="tool-rich-label">{tool.toolName || '?'}</span>
      </div>
      {open && (
        <div className="tool-rich-detail">
          {argsStr && <code className="log-tool-args">{argsStr}</code>}
          {tool.result && <div className="log-tool-result">{tool.result}</div>}
        </div>
      )}
    </div>
  )
}

export default function ToolItemRenderer({ tool }: { tool: ToolEntry }) {
  const name = tool.toolName || ''
  if (FILE_TOOLS.has(name)) return <FileWriteItem tool={tool} />
  if (READ_TOOLS.has(name)) return <FileReadItem tool={tool} />
  if (EXEC_TOOLS.has(name)) return <TerminalItem tool={tool} />
  if (SEARCH_TOOLS.has(name)) return <SearchItem tool={tool} />
  return <GenericItem tool={tool} />
}
