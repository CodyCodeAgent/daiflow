import { useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useTheme } from '../../hooks/useTheme'

interface MarkdownViewerProps {
  content: string
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }).catch(() => {})
  }, [text])

  return (
    <button
      onClick={handleCopy}
      style={{
        position: 'absolute', top: 6, right: 6,
        background: 'var(--bg-4)', border: '1px solid var(--border)',
        borderRadius: '4px', padding: '2px 8px',
        fontSize: '10px', color: copied ? 'var(--green)' : 'var(--t2)',
        cursor: 'pointer', opacity: 0, transition: 'opacity 0.15s',
        fontFamily: 'var(--mono)',
      }}
      className="md-copy-btn"
    >
      {copied ? '✓' : 'Copy'}
    </button>
  )
}

export default function MarkdownViewer({ content }: MarkdownViewerProps) {
  const { theme } = useTheme()
  const highlightStyle = theme === 'dark' ? oneDark : oneLight

  return (
    <div className="markdown-content" style={{ fontSize: '13px', lineHeight: 1.7, color: 'var(--t1)' }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const code = String(children).replace(/\n$/, '')
            if (match) {
              return (
                <div style={{ position: 'relative' }} className="md-code-wrapper">
                  <CopyButton text={code} />
                  <SyntaxHighlighter
                    style={highlightStyle}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{ borderRadius: '6px', fontSize: '12px', margin: '8px 0' }}
                  >
                    {code}
                  </SyntaxHighlighter>
                </div>
              )
            }
            return (
              <code className={className} {...props}
                style={{ background: 'var(--bg-3)', padding: '1px 5px', borderRadius: '4px', fontFamily: 'var(--mono)', fontSize: '12px' }}
              >
                {children}
              </code>
            )
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
