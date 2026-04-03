import { useState, useEffect } from 'react'
import Topbar from '../../components/Shell/Topbar'
import {
  getSettings, updateSettings,
  listRunners, createRunner, updateRunner, deleteRunner,
  setDefaultRunner, testRunnerConfig, testRunnerById,
} from '../../api'
import type { RunnerConfigData, RunnerConfigCreateData } from '../../api'
import { useTheme } from '../../hooks/useTheme'
import { useLocale } from '../../hooks/useLocale'
import { useSettingsContext } from '../../App'
import { useToast } from '../../components/Toast/ToastContext'
import Modal from '../../components/Modal/Modal'
import type { Locale } from '../../i18n'
import './Settings.css'

type RunnerType = 'cody' | 'claude_code' | 'cursor'

interface RunnerFormState {
  type: RunnerType
  name: string
  // Cody
  model: string
  base_url: string
  api_key: string
  // Claude Code / Cursor
  claude_api_key: string
  claude_model: string
  cursor_api_key: string
  cursor_model: string
  max_turns: string
}

const defaultForm = (): RunnerFormState => ({
  type: 'cody',
  name: '',
  model: '',
  base_url: '',
  api_key: '',
  claude_api_key: '',
  claude_model: '',
  cursor_api_key: '',
  cursor_model: '',
  max_turns: '',
})

function formToPayload(form: RunnerFormState): RunnerConfigCreateData {
  let config: Record<string, string> = {}
  if (form.type === 'cody') {
    config = { model: form.model, base_url: form.base_url, api_key: form.api_key }
  } else if (form.type === 'claude_code') {
    config = { api_key: form.claude_api_key, model: form.claude_model, max_turns: form.max_turns }
  } else {
    config = { api_key: form.cursor_api_key, model: form.cursor_model, max_turns: form.max_turns }
  }
  return { type: form.type, name: form.name, config }
}

function runnerToForm(rc: RunnerConfigData): RunnerFormState {
  const cfg = rc.config || {}
  if (rc.type === 'cody') {
    return { ...defaultForm(), type: 'cody', name: rc.name, model: cfg.model || '', base_url: cfg.base_url || '', api_key: cfg.api_key || '' }
  } else if (rc.type === 'claude_code') {
    return { ...defaultForm(), type: 'claude_code', name: rc.name, claude_api_key: cfg.api_key || '', claude_model: cfg.model || '', max_turns: cfg.max_turns || '' }
  } else {
    return { ...defaultForm(), type: 'cursor', name: rc.name, cursor_api_key: cfg.api_key || '', cursor_model: cfg.model || '', max_turns: cfg.max_turns || '' }
  }
}

const TYPE_LABELS: Record<RunnerType, string> = {
  cody: 'Cody SDK',
  claude_code: 'Claude Code',
  cursor: 'Cursor Agent',
}

export default function Settings() {
  const { theme, toggleTheme } = useTheme()
  const { locale, setLocale, t } = useLocale()
  const { recheck } = useSettingsContext()
  const toast = useToast()

  // Runners state
  const [runners, setRunners] = useState<RunnerConfigData[]>([])
  const [runnersLoading, setRunnersLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRunner, setEditingRunner] = useState<RunnerConfigData | null>(null)
  const [form, setForm] = useState<RunnerFormState>(defaultForm())
  const [testingId, setTestingId] = useState<string | null>(null)
  const [formTestState, setFormTestState] = useState<'idle' | 'testing' | 'ok' | 'error'>('idle')
  const [formTestError, setFormTestError] = useState('')
  const [saving, setSaving] = useState(false)

  // Tool approval mode
  const [approvalMode, setApprovalMode] = useState<'auto' | 'high_risk' | 'all'>('auto')

  const loadRunners = () => {
    setRunnersLoading(true)
    listRunners().then(setRunners).catch(() => setRunners([])).finally(() => setRunnersLoading(false))
  }

  useEffect(() => {
    loadRunners()
    getSettings().then(data => {
      if (data.language && (data.language === 'en' || data.language === 'zh')) {
        setLocale(data.language as Locale)
      }
      if (data.tool_approval_mode && ['auto', 'high_risk', 'all'].includes(data.tool_approval_mode)) {
        setApprovalMode(data.tool_approval_mode as 'auto' | 'high_risk' | 'all')
      }
    }).catch(() => {})
  }, [])

  const openAdd = () => {
    setEditingRunner(null)
    setForm(defaultForm())
    setFormTestState('idle')
    setFormTestError('')
    setModalOpen(true)
  }

  const openEdit = (rc: RunnerConfigData) => {
    setEditingRunner(rc)
    setForm(runnerToForm(rc))
    setFormTestState('idle')
    setFormTestError('')
    setModalOpen(true)
  }

  const handleSaveRunner = async () => {
    setSaving(true)
    try {
      const payload = formToPayload(form)
      if (editingRunner) {
        await updateRunner(editingRunner.id, { name: payload.name, config: payload.config })
        toast.success('Runner updated')
      } else {
        await createRunner(payload)
        toast.success('Runner added')
      }
      setModalOpen(false)
      loadRunners()
      recheck()
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleTestForm = async () => {
    setFormTestState('testing')
    setFormTestError('')
    try {
      if (editingRunner) {
        await testRunnerById(editingRunner.id)
      } else {
        await testRunnerConfig(formToPayload(form))
      }
      setFormTestState('ok')
    } catch (err: any) {
      setFormTestState('error')
      setFormTestError(err.message || 'Test failed')
    }
  }

  const handleTestExisting = async (rc: RunnerConfigData) => {
    setTestingId(rc.id)
    try {
      await testRunnerById(rc.id)
      toast.success(`${rc.name}: ${t('runners.test_ok')}`)
    } catch (err: any) {
      toast.error(`${rc.name}: ${err.message}`)
    } finally {
      setTestingId(null)
    }
  }

  const handleSetDefault = async (rc: RunnerConfigData) => {
    try {
      await setDefaultRunner(rc.id)
      loadRunners()
      recheck()
    } catch (err: any) { toast.error(err.message) }
  }

  const handleDelete = async (rc: RunnerConfigData) => {
    if (!confirm(t('runners.delete_confirm'))) return
    try {
      await deleteRunner(rc.id)
      loadRunners()
      recheck()
    } catch (err: any) { toast.error(err.message) }
  }

  const handleLocaleChange = (newLocale: Locale) => {
    setLocale(newLocale)
    updateSettings({ language: newLocale }).catch(() => {})
  }

  const handleApprovalModeChange = (mode: 'auto' | 'high_risk' | 'all') => {
    setApprovalMode(mode)
    updateSettings({ tool_approval_mode: mode }).catch(() => {})
  }

  const f = (field: keyof RunnerFormState, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }))
    if (formTestState !== 'idle') { setFormTestState('idle'); setFormTestError('') }
  }

  return (
    <>
      <Topbar title={t('settings.title')} />
      <div className="content">
        <div className="settings-page">
          <div className="eyebrow">{t('settings.eyebrow')}</div>
          <h1 className="page-title">{t('runners.section_title')}</h1>
          <p className="page-desc">{t('runners.desc')}</p>

          {/* Runner list */}
          <div className="card settings-card runners-card">
            {runnersLoading ? (
              <div className="runners-empty">Loading…</div>
            ) : runners.length === 0 ? (
              <div className="runners-empty">{t('runners.empty')}</div>
            ) : (
              <div className="runners-list">
                {runners.map(rc => (
                  <div key={rc.id} className="runner-row">
                    <div className="runner-info">
                      <div className="runner-name">
                        {rc.name}
                        {rc.is_default && <span className="runner-default-badge">{t('runners.default_badge')}</span>}
                      </div>
                      <div className="runner-meta">
                        <span className="runner-type-tag">{TYPE_LABELS[rc.type as RunnerType] || rc.type}</span>
                        {rc.config.model && <span className="runner-model">{rc.config.model}</span>}
                      </div>
                    </div>
                    <div className="runner-actions">
                      {!rc.is_default && (
                        <button className="btn btn-ghost btn-sm" onClick={() => handleSetDefault(rc)}>
                          {t('runners.set_default')}
                        </button>
                      )}
                      <button
                        className="btn btn-ghost btn-sm"
                        disabled={testingId === rc.id}
                        onClick={() => handleTestExisting(rc)}
                      >
                        {testingId === rc.id ? t('runners.testing') : t('runners.test')}
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={() => openEdit(rc)}>
                        {t('runners.edit')}
                      </button>
                      <button className="btn btn-ghost btn-sm btn-danger" onClick={() => handleDelete(rc)}>
                        {t('runners.delete')}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="runners-footer">
              <button className="btn btn-primary btn-sm" onClick={openAdd}>
                {t('runners.add')}
              </button>
            </div>
          </div>

          <div className="section-head">{t('settings.preferences')}</div>
          <div className="card settings-card prefs-card">
            <div className="pref-row">
              <div className="pref-label">{t('settings.appearance')}</div>
              <div className="seg-control">
                <button className={`seg-btn ${theme === 'dark' ? 'active' : ''}`} onClick={() => { if (theme !== 'dark') toggleTheme() }}>
                  🌙 {t('settings.dark')}
                </button>
                <button className={`seg-btn ${theme === 'light' ? 'active' : ''}`} onClick={() => { if (theme !== 'light') toggleTheme() }}>
                  ☀️ {t('settings.light')}
                </button>
              </div>
            </div>
            <div className="pref-row">
              <div className="pref-label">{t('settings.language')}</div>
              <div className="seg-control">
                <button className={`seg-btn ${locale === 'en' ? 'active' : ''}`} onClick={() => handleLocaleChange('en')}>
                  English
                </button>
                <button className={`seg-btn ${locale === 'zh' ? 'active' : ''}`} onClick={() => handleLocaleChange('zh')}>
                  中文
                </button>
              </div>
            </div>
          </div>

          <div className="section-head">{t('settings.tool_approval')}</div>
          <div className="theme-switch">
            <div className={`theme-option ${approvalMode === 'auto' ? 'selected' : ''}`} onClick={() => handleApprovalModeChange('auto')}>
              <div className="theme-option-icon">&#9889;</div>
              <div className="theme-option-label">{t('settings.approval_auto')}</div>
            </div>
            <div className={`theme-option ${approvalMode === 'high_risk' ? 'selected' : ''}`} onClick={() => handleApprovalModeChange('high_risk')}>
              <div className="theme-option-icon">&#9888;</div>
              <div className="theme-option-label">{t('settings.approval_high_risk')}</div>
            </div>
            <div className={`theme-option ${approvalMode === 'all' ? 'selected' : ''}`} onClick={() => handleApprovalModeChange('all')}>
              <div className="theme-option-icon">&#128274;</div>
              <div className="theme-option-label">{t('settings.approval_all')}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Add / Edit Runner Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)}>
        <div className="runner-modal-body">
          <h2 className="runner-modal-title">{editingRunner ? t('runners.modal_edit_title') : t('runners.modal_add_title')}</h2>
          {/* Type selector — only shown when adding */}
          {!editingRunner && (
            <div className="field">
              <label className="field-label">{t('runners.type_label')}</label>
              <div className="runner-type-grid">
                {(['cody', 'claude_code', 'cursor'] as RunnerType[]).map(rt => (
                  <div
                    key={rt}
                    className={`runner-type-card ${form.type === rt ? 'selected' : ''}`}
                    onClick={() => f('type', rt)}
                  >
                    <div className="runner-type-card-name">{TYPE_LABELS[rt]}</div>
                    <div className="runner-type-card-desc">{t(`runners.type_${rt}_desc` as any)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="field">
            <label className="field-label">{t('runners.name')}</label>
            <input className="input" placeholder={t('runners.name_placeholder')} value={form.name} onChange={e => f('name', e.target.value)} />
          </div>

          {/* Cody-specific fields */}
          {form.type === 'cody' && (
            <>
              <div className="field">
                <label className="field-label">{t('runners.model')}</label>
                <input className="input" placeholder={t('runners.model_placeholder')} value={form.model} onChange={e => f('model', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">{t('runners.base_url')}</label>
                <input className="input" placeholder={t('runners.base_url_placeholder')} value={form.base_url} onChange={e => f('base_url', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">{t('runners.api_key')}</label>
                <input className="input" type="password" placeholder={t('runners.api_key_placeholder')} value={form.api_key} onChange={e => f('api_key', e.target.value)} />
              </div>
            </>
          )}

          {/* Claude Code fields */}
          {form.type === 'claude_code' && (
            <>
              <div className="field">
                <label className="field-label">{t('runners.api_key_anthropic')}</label>
                <input className="input" type="password" placeholder="sk-ant-..." value={form.claude_api_key} onChange={e => f('claude_api_key', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">{t('runners.model_optional')}</label>
                <input className="input" placeholder="claude-sonnet-4-6" value={form.claude_model} onChange={e => f('claude_model', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">{t('runners.max_turns')}</label>
                <input className="input" type="number" placeholder="50" value={form.max_turns} onChange={e => f('max_turns', e.target.value)} />
              </div>
            </>
          )}

          {/* Cursor fields */}
          {form.type === 'cursor' && (
            <>
              <div className="field">
                <label className="field-label">{t('runners.api_key_cursor')}</label>
                <input className="input" type="password" placeholder="cursor_..." value={form.cursor_api_key} onChange={e => f('cursor_api_key', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">{t('runners.model_optional')}</label>
                <input className="input" placeholder="claude-sonnet-4-6" value={form.cursor_model} onChange={e => f('cursor_model', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">{t('runners.max_turns')}</label>
                <input className="input" type="number" placeholder="50" value={form.max_turns} onChange={e => f('max_turns', e.target.value)} />
              </div>
            </>
          )}

          {formTestState === 'ok' && <div className="test-result test-ok">{t('runners.test_ok')}</div>}
          {formTestState === 'error' && <div className="test-result test-fail">{formTestError}</div>}

          <div className="actions">
            <button
              className="btn btn-primary"
              disabled={saving}
              onClick={handleSaveRunner}
            >
              {saving ? t('runners.saving') : t('runners.save')}
            </button>
            <button
              className="btn btn-ghost"
              disabled={formTestState === 'testing'}
              onClick={handleTestForm}
            >
              {formTestState === 'testing' ? t('runners.testing') : t('runners.test')}
            </button>
            <button className="btn btn-ghost" onClick={() => setModalOpen(false)}>{t('runners.cancel')}</button>
          </div>
        </div>
      </Modal>
    </>
  )
}
