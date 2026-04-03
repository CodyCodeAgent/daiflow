export const BASE = '/api'

/** Default request timeout in milliseconds. */
const REQUEST_TIMEOUT_MS = 30_000

export async function request<T = unknown>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      signal: controller.signal,
    })
    if (!res.ok) {
      let detail = `API error: ${res.status}`
      try {
        const body = await res.json()
        if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch {
        // Response body is not JSON — keep the status-based message
      }
      throw new Error(detail)
    }
    return res.json()
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`Request timeout: ${path}`)
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
}
