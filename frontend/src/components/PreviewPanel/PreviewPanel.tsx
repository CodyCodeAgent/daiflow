import { useState } from 'react'
import { useLocale } from '../../hooks/useLocale'
import './PreviewPanel.css'

interface PreviewPanelProps {
  /** URL used as the iframe src (may be proxied) */
  url: string
  /** Original URL shown in the toolbar (defaults to url) */
  displayUrl?: string
  refreshKey: number
  onClose: () => void
  onRefresh: () => void
  onOpenExternal: () => void
}

export default function PreviewPanel({ url, displayUrl, refreshKey, onClose, onRefresh, onOpenExternal }: PreviewPanelProps) {
  const { t } = useLocale()
  const [loading, setLoading] = useState(true)
  const shownUrl = displayUrl || url

  return (
    <div className="preview-panel">
      <div className="preview-toolbar">
        <span className="preview-url" title={shownUrl}>{shownUrl}</span>
        <div className="preview-actions">
          <button className="preview-action-btn" onClick={onRefresh} title={t('devserver.refresh')}>↻</button>
          <button className="preview-action-btn" onClick={onOpenExternal} title={t('devserver.open_external')}>↗</button>
          <button className="preview-action-btn" onClick={onClose} title={t('devserver.close_preview')}>✕</button>
        </div>
      </div>
      <div className="preview-frame-wrapper">
        {loading && (
          <div className="preview-loading">
            <div className="spinner" />
            <span>{t('preview.loading')}</span>
          </div>
        )}
        <iframe
          key={refreshKey}
          className="preview-iframe"
          src={url}
          title="Dev Server Preview"
          onLoad={() => setLoading(false)}
        />
      </div>
    </div>
  )
}
