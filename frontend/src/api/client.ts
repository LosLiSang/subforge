let csrfToken: string | null = null

export async function getCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken
  try {
    const res = await fetch('/api/session')
    if (res.ok) {
      const data = await res.json()
      csrfToken = data.csrf_token || ''
      return csrfToken || ''
    }
  } catch (err) {
    console.error('Failed to fetch session csrf:', err)
  }
  return ''
}

export async function apiRequest<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers || {})
  
  const method = (options.method || 'GET').toUpperCase()
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    const token = await getCsrfToken()
    if (token && !headers.has('x-csrf-token')) {
      headers.set('x-csrf-token', token)
    }
  }
  
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }
  
  if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(endpoint, {
    ...options,
    headers,
    credentials: 'same-origin',
  })

  if (!response.ok) {
    let errorMessage = `HTTP Error ${response.status}`
    try {
      const errJson = await response.json()
      errorMessage = errJson.error || errJson.message || errorMessage
    } catch {
      try {
        const errText = await response.text()
        if (errText) errorMessage = errText
      } catch {}
    }
    throw new Error(errorMessage)
  }

  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return (await response.json()) as T
  }
  return (await response.text()) as unknown as T
}

export const api = {
  get: <T = any>(url: string) => apiRequest<T>(url, { method: 'GET' }),
  post: <T = any>(url: string, body?: any) =>
    apiRequest<T>(url, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: <T = any>(url: string, body?: any) =>
    apiRequest<T>(url, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),
}
