import { useState, useEffect } from 'react'
import MarkdownViewer from '../MarkdownViewer/MarkdownViewer'
import { getTaskArtifact } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import './ConstitutionDrawer.css'

interface ConstitutionDrawerProps {
  taskId: string
}

export default function ConstitutionDrawer({ taskId }: ConstitutionDrawerProps) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const handleOpen = () => {
    setOpen(true)
    if (!loaded) {
      setLoading(true)
      getTaskArtifact(taskId, 'constitution')
        .then(res => setContent(res.exists ? res.content : null))
        .catch(() => setContent(null))
        .finally(() => { setLoading(false); setLoaded(true) })
    }
  }

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open])

  return (
    <>
      {/* Floating trigger button */}
      <button
        className="constitution-trigger"
        onClick={handleOpen}
        title={t('constitution.title')}
      >
        <span className="constitution-trigger-icon">§</span>
        <span className="constitution-trigger-label">{t('constitution.button')}</span>
      </button>

      {/* Backdrop */}
      {open && (
        <div className="constitution-backdrop" onClick={() => setOpen(false)} />
      )}

      {/* Drawer */}
      <div className={`constitution-drawer ${open ? 'open' : ''}`}>
        <div className="constitution-drawer-header">
          <div>
            <div className="constitution-drawer-title">{t('constitution.title')}</div>
            <div className="constitution-drawer-desc">{t('constitution.desc')}</div>
          </div>
          <button className="constitution-close-btn" onClick={() => setOpen(false)}>✕</button>
        </div>
        <div className="constitution-drawer-body">
          {loading ? (
            <div className="constitution-loading">{t('constitution.loading')}</div>
          ) : content ? (
            <MarkdownViewer content={content} />
          ) : (
            <div className="constitution-empty">
              <div className="constitution-empty-icon">§</div>
              <p>{t('constitution.not_found')}</p>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
