import { useState, useEffect, useCallback } from 'react'
import Topbar from '../../components/Shell/Topbar'
import {
  listMcpServers, createMcpServer, updateMcpServer, deleteMcpServer, testMcpServer,
  type McpServerData,
} from '../../api'
import { useLocale } from '../../hooks/useLocale'
import { useToast } from '../../components/Toast/ToastContext'
import './McpServers.css'

function parseHeaders(raw: string): Record<string, string> {
  if (!raw.trim()) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    throw new Error('Invalid JSON in headers field')
  }
  if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
    throw new Error('Headers must be a JSON object, e.g. {"key": "value"}')
  }
  return parsed as Record<string, string>
}

type McpTestState = 'idle' | 'testing' | 'ok' | 'error'

function McpForm({ form, setForm, t, onSave, onCancel }: {
  form: { name: string; url: string; headers: string; enabled: boolean }
  setForm: (f: typeof form) => void
  t: (k: any) => string
  onSave: () => void
  onCancel: () => void
}) {
  const [mcpTestState, setMcpTestState] = useState<McpTestState>('idle')
  const [mcpTestMsg, setMcpTestMsg] = useState('')
  const valid = form.name.trim() && form.url.trim()

  const handleTest = async () => {
    setMcpTestState('testing')
    setMcpTestMsg('')
    try {
      const headers = parseHeaders(form.headers)
      const result = await testMcpServer({ url: form.url, headers })
      const info = [result.server_name, result.server_version].filter(Boolean).join(' ')
      setMcpTestState('ok')
      setMcpTestMsg(info ? `${t('mcp.test_ok')} — ${info}` : t('mcp.test_ok'))
    } catch (err: any) {
      setMcpTestState('error')
      setMcpTestMsg(err.message || t('mcp.test_fail'))
    }
  }

  return (
    <div className="mcp-form">
      <div className="field">
        <label className="field-label">{t('mcp.name')}</label>
        <input className="input" placeholder={t('mcp.name_placeholder')} value={form.name}
          onChange={e => { setForm({ ...form, name: e.target.value }); setMcpTestState('idle') }} />
      </div>
      <div className="field">
        <label className="field-label">{t('mcp.url')}</label>
        <input className="input" placeholder={t('mcp.url_placeholder')} value={form.url}
          onChange={e => { setForm({ ...form, url: e.target.value }); setMcpTestState('idle') }} />
      </div>
      <div className="field">
        <label className="field-label">{t('mcp.headers')}</label>
        <textarea className="input mcp-headers-input" placeholder={t('mcp.headers_placeholder')} value={form.headers}
          onChange={e => { setForm({ ...form, headers: e.target.value }); setMcpTestState('idle') }} rows={3} />
      </div>
      {mcpTestState === 'ok' && <div className="test-result test-ok">{mcpTestMsg}</div>}
      {mcpTestState === 'error' && <div className="test-result test-fail">{mcpTestMsg}</div>}
      <div className="actions">
        <button className="btn btn-primary btn-sm" onClick={onSave} disabled={!valid || mcpTestState === 'testing'}>{t('mcp.save')}</button>
        <button className="btn btn-ghost btn-sm" onClick={handleTest}
          disabled={!form.url.trim() || mcpTestState === 'testing'}>
          {mcpTestState === 'testing' ? t('mcp.testing') : t('mcp.test')}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>{t('mcp.cancel')}</button>
      </div>
    </div>
  )
}

function ToggleSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      className={`toggle-switch ${checked ? 'on' : ''}`}
      onClick={() => onChange(!checked)}
      type="button"
    >
      <span className="toggle-knob" />
    </button>
  )
}

export default function McpServers() {
  const { t } = useLocale()
  const toast = useToast()
  const [mcpServers, setMcpServers] = useState<McpServerData[]>([])
  const [mcpEditing, setMcpEditing] = useState<string | null>(null)
  const [mcpForm, setMcpForm] = useState({ name: '', url: '', headers: '', enabled: true })

  const loadMcpServers = useCallback(() => {
    listMcpServers().then(setMcpServers).catch(() => {})
  }, [])

  useEffect(() => {
    loadMcpServers()
  }, [loadMcpServers])

  const handleToggle = async (srv: McpServerData) => {
    try {
      await updateMcpServer(srv.id, { enabled: !srv.enabled })
      loadMcpServers()
    } catch (err: any) { toast.error(err.message) }
  }

  return (
    <>
      <Topbar
        title={t('mcp.title')}
        actions={
          mcpEditing !== 'new' ? (
            <button className="btn btn-primary btn-sm" onClick={() => {
              setMcpEditing('new')
              setMcpForm({ name: '', url: '', headers: '', enabled: true })
            }}>{t('mcp.add')}</button>
          ) : undefined
        }
      />
      <div className="content">
        <div className="mcp-page">
          <p className="page-desc">{t('mcp.desc')}</p>

          {/* User-added MCP servers */}
          {mcpServers.map(srv => (
            <div key={srv.id} className="card mcp-server-card">
              {mcpEditing === srv.id ? (
                <McpForm
                  form={mcpForm}
                  setForm={setMcpForm}
                  t={t}
                  onSave={async () => {
                    try {
                      const headers = parseHeaders(mcpForm.headers)
                      await updateMcpServer(srv.id, { name: mcpForm.name, url: mcpForm.url, headers, enabled: mcpForm.enabled })
                      setMcpEditing(null)
                      loadMcpServers()
                    } catch (err: any) { toast.error(err.message) }
                  }}
                  onCancel={() => setMcpEditing(null)}
                />
              ) : (
                <div className="mcp-server-row">
                  <div className="mcp-server-info">
                    <span className={`mcp-status-dot ${srv.enabled ? 'active' : ''}`} />
                    <strong>{srv.name}</strong>
                    <span className="mcp-server-url">{srv.url}</span>
                  </div>
                  <div className="mcp-server-actions">
                    <ToggleSwitch checked={srv.enabled} onChange={() => handleToggle(srv)} />
                    <button className="btn btn-sm btn-ghost" onClick={() => {
                      setMcpEditing(srv.id)
                      setMcpForm({
                        name: srv.name,
                        url: srv.url,
                        headers: Object.keys(srv.headers).length ? JSON.stringify(srv.headers, null, 2) : '',
                        enabled: srv.enabled,
                      })
                    }}>{t('projects.edit')}</button>
                    <button className="btn btn-sm btn-ghost" onClick={async () => {
                      if (!confirm(t('mcp.delete_confirm'))) return
                      try {
                        await deleteMcpServer(srv.id)
                        loadMcpServers()
                      } catch (err: any) { toast.error(err.message) }
                    }}>{t('mcp.delete')}</button>
                  </div>
                </div>
              )}
            </div>
          ))}

          {mcpEditing === 'new' && (
            <div className="card mcp-server-card">
              <McpForm
                form={mcpForm}
                setForm={setMcpForm}
                t={t}
                onSave={async () => {
                  try {
                    const headers = parseHeaders(mcpForm.headers)
                    await createMcpServer({ name: mcpForm.name, url: mcpForm.url, headers, enabled: mcpForm.enabled })
                    setMcpEditing(null)
                    loadMcpServers()
                  } catch (err: any) { toast.error(err.message) }
                }}
                onCancel={() => setMcpEditing(null)}
              />
            </div>
          )}
        </div>
      </div>
    </>
  )
}
