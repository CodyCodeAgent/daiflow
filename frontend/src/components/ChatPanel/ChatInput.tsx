import { useState, useRef, useCallback, useEffect } from 'react'
import { listTaskFiles, uploadChatImage } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import type { ChatSendOptions } from './ChatPanel'
import './ChatInput.css'

interface ChatInputProps {
  onSend: (text: string, opts?: ChatSendOptions) => void
  disabled?: boolean
  taskId?: string
  placeholder?: string
  responding?: boolean
  cancelling?: boolean
  onStop?: () => void
}

interface MentionFile {
  path: string
}

export default function ChatInput({
  onSend, disabled = false, taskId, placeholder,
  responding = false, cancelling = false, onStop,
}: ChatInputProps) {
  const { t } = useLocale()
  const inputLocked = disabled || responding
  const [input, setInput] = useState('')
  const [mentionActive, setMentionActive] = useState(false)
  const [mentionQuery, setMentionQuery] = useState('')
  const [mentionFiles, setMentionFiles] = useState<MentionFile[]>([])
  const [mentionIdx, setMentionIdx] = useState(0)
  const [attachedFiles, setAttachedFiles] = useState<string[]>([])
  const [attachedImages, setAttachedImages] = useState<{ name: string; path: string }[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const mentionRef = useRef<HTMLDivElement>(null)

  const mentionGenRef = useRef(0)
  useEffect(() => {
    if (!mentionActive || !taskId) {
      setMentionFiles([])
      return
    }
    const gen = ++mentionGenRef.current
    const timer = setTimeout(() => {
      listTaskFiles(taskId, mentionQuery)
        .then(data => {
          if (gen !== mentionGenRef.current) return // stale response
          setMentionFiles(data.files.map(f => ({ path: f })))
          setMentionIdx(0)
        })
        .catch(() => {
          if (gen === mentionGenRef.current) setMentionFiles([])
        })
    }, 150)
    return () => clearTimeout(timer)
  }, [mentionActive, mentionQuery, taskId])

  // Auto-resize textarea height
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 150) + 'px'
  }, [input])

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    setInput(val)

    const pos = e.target.selectionStart ?? val.length
    const before = val.slice(0, pos)
    const atMatch = before.match(/@([^\s@]*)$/)

    if (atMatch && taskId) {
      setMentionActive(true)
      setMentionQuery(atMatch[1])
    } else {
      setMentionActive(false)
    }
  }, [taskId])

  const insertMention = useCallback((filePath: string) => {
    const pos = textareaRef.current?.selectionStart ?? input.length
    const before = input.slice(0, pos)
    const after = input.slice(pos)
    const atPos = before.lastIndexOf('@')
    const newBefore = before.slice(0, atPos) + `@${filePath} `
    setInput(newBefore + after)
    setMentionActive(false)
    setAttachedFiles(prev => prev.includes(filePath) ? prev : [...prev, filePath])
    setTimeout(() => textareaRef.current?.focus(), 0)
  }, [input])

  const removeMention = useCallback((filePath: string) => {
    setAttachedFiles(prev => prev.filter(f => f !== filePath))
    setInput(prev => prev.replace(new RegExp(`@${filePath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s?`, 'g'), ''))
  }, [])

  const removeImage = useCallback((idx: number) => {
    setAttachedImages(prev => prev.filter((_, i) => i !== idx))
  }, [])

  const handleSend = useCallback(() => {
    if (inputLocked || !input.trim()) return
    const contextFiles = attachedFiles.length > 0 ? [...attachedFiles] : undefined
    const images = attachedImages.length > 0 ? attachedImages.map(i => i.path) : undefined
    onSend(input.trim(), { contextFiles, images })
    setInput('')
    setAttachedFiles([])
    setAttachedImages([])
    setMentionActive(false)
  }, [inputLocked, input, attachedFiles, attachedImages, onSend])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (mentionActive && mentionFiles.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIdx(i => (i + 1) % mentionFiles.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIdx(i => (i - 1 + mentionFiles.length) % mentionFiles.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        insertMention(mentionFiles[mentionIdx].path)
        return
      }
      if (e.key === 'Escape') {
        setMentionActive(false)
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!inputLocked) handleSend()
    }
  }, [mentionActive, mentionFiles, mentionIdx, insertMention, inputLocked, handleSend])

  const handlePaste = useCallback(async (e: React.ClipboardEvent) => {
    if (!taskId) return
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault()
        const file = item.getAsFile()
        if (!file) continue
        try {
          const result = await uploadChatImage(taskId, file)
          setAttachedImages(prev => [...prev, { name: file.name || 'pasted-image', path: result.path }])
        } catch (err) {
          console.error('Image upload failed:', err)
        }
        return
      }
    }
  }, [taskId])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    if (!taskId) return
    e.preventDefault()
    const files = e.dataTransfer?.files
    if (!files) return
    const imageFiles = Array.from(files).filter(f => f.type.startsWith('image/'))
    if (imageFiles.length === 0) return
    // Upload all images concurrently but preserve order via Promise.all
    const results = await Promise.allSettled(
      imageFiles.map(file => uploadChatImage(taskId, file).then(r => ({ name: file.name, path: r.path })))
    )
    const uploaded = results
      .filter((r): r is PromiseFulfilledResult<{ name: string; path: string }> => r.status === 'fulfilled')
      .map(r => r.value)
    if (uploaded.length > 0) {
      setAttachedImages(prev => [...prev, ...uploaded])
    }
  }, [taskId])

  const hasAttachments = attachedFiles.length > 0 || attachedImages.length > 0

  return (
    <div className="ci-wrapper" onDrop={handleDrop} onDragOver={e => e.preventDefault()}>
      <div className={`ci-box${disabled ? ' ci-disabled' : ''}`}>
        {/* Mention popup — positioned above the box */}
        {mentionActive && mentionFiles.length > 0 && (
          <div className="ci-mention-popup" ref={mentionRef}>
            {mentionFiles.map((f, i) => (
              <div
                key={f.path}
                className={`ci-mention-item${i === mentionIdx ? ' active' : ''}`}
                onMouseDown={e => { e.preventDefault(); insertMention(f.path) }}
              >
                <svg className="ci-mention-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M3 2h7l3 3v8a1 1 0 01-1 1H3a1 1 0 01-1-1V3a1 1 0 011-1z" stroke="currentColor" strokeWidth="1.2"/>
                  <path d="M10 2v3h3" stroke="currentColor" strokeWidth="1.2"/>
                </svg>
                <span className="ci-mention-path">{f.path}</span>
              </div>
            ))}
          </div>
        )}

        {/* Attachments */}
        {hasAttachments && (
          <div className="ci-attachments">
            {attachedFiles.map(f => (
              <span key={f} className="ci-chip">
                <span className="ci-chip-at">@</span>
                <span className="ci-chip-text">{f.split('/').pop()}</span>
                <button className="ci-chip-rm" onClick={() => removeMention(f)}>&times;</button>
              </span>
            ))}
            {attachedImages.map((img, i) => (
              <span key={i} className="ci-chip ci-chip-img">
                <svg className="ci-chip-imgicon" width="12" height="12" viewBox="0 0 16 16" fill="none">
                  <rect x="1" y="2" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.2"/>
                  <circle cx="5.5" cy="6.5" r="1.5" fill="currentColor"/>
                  <path d="M1 11l3.5-3.5L8 11l3-4 4 4" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
                </svg>
                <span className="ci-chip-text">{img.name}</span>
                <button className="ci-chip-rm" onClick={() => removeImage(i)}>&times;</button>
              </span>
            ))}
          </div>
        )}

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          className="ci-textarea"
          placeholder={placeholder}
          rows={1}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          disabled={inputLocked}
        />

        {/* Bottom bar: hints + send or stop while streaming */}
        <div className="ci-bar">
          <div className="ci-hints">
            {taskId && (
              <span className="ci-hint" title="Type @ to mention files">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                  <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.2"/>
                  <path d="M10.5 8a2.5 2.5 0 10-1.25 2.17" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
                </svg>
              </span>
            )}
            <span className="ci-hint-text">Enter to send, Shift+Enter for newline</span>
          </div>
          {responding && onStop ? (
            cancelling ? (
              <button type="button" className="ci-send ci-send-stopping" disabled aria-label={t('chat.stop')}>
                <span className="ci-btn-spinner" />
              </button>
            ) : (
              <button
                type="button"
                className="ci-send ci-send-stop"
                onClick={onStop}
                title={t('chat.stop')}
                aria-label={t('chat.stop')}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              </button>
            )
          ) : (
            <button
              className={`ci-send${input.trim() ? ' ci-send-active' : ''}`}
              onClick={handleSend}
              disabled={inputLocked || !input.trim()}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M6 12L3.27 3.13a.5.5 0 01.64-.64L21 12 3.91 21.51a.5.5 0 01-.64-.64L6 12zm0 0h9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
