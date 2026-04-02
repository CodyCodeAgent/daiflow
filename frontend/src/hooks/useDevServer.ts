import { useState, useEffect, useCallback, useRef } from 'react'
import { startDevServer, stopDevServer, getDevServerStatus, type DevServerStatus } from '../api'

interface UseDevServerResult {
  status: DevServerStatus | null
  starting: boolean
  start: () => Promise<void>
  stop: () => Promise<void>
  openPreview: () => void
  error: string | null
}

function getPreviewUrl(s: DevServerStatus): string {
  return s.preview_url || s.url || ''
}

export function useDevServer(taskId: string): UseDevServerResult {
  const [status, setStatus] = useState<DevServerStatus | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    getDevServerStatus(taskId)
      .then(s => { if (mountedRef.current) setStatus(s) })
      .catch(() => {})
    return () => { mountedRef.current = false }
  }, [taskId])

  const start = useCallback(async () => {
    setStarting(true)
    setError(null)
    try {
      const s = await startDevServer(taskId)
      if (mountedRef.current) {
        setStatus(s)
        const url = getPreviewUrl(s)
        if (s.running && url) window.open(url, '_blank')
      }
    } catch (e: any) {
      if (mountedRef.current) setError(e.message || 'Start failed')
    } finally {
      if (mountedRef.current) setStarting(false)
    }
  }, [taskId])

  const stop = useCallback(async () => {
    try {
      await stopDevServer(taskId)
      if (mountedRef.current) setStatus({ running: false, url: '', port: 0, preview_url: '' })
    } catch {
      // ignore
    }
  }, [taskId])

  const openPreview = useCallback(() => {
    if (status) {
      const url = getPreviewUrl(status)
      if (url) window.open(url, '_blank')
    }
  }, [status])

  return { status, starting, start, stop, openPreview, error }
}
