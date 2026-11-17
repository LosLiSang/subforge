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
  post: <T = any>(url: string, body?: any) => {
    const isForm = body instanceof FormData || body instanceof URLSearchParams
    return apiRequest<T>(url, {
      method: 'POST',
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
    })
  },
  postForm: <T = any>(url: string, form: FormData | Record<string, any>) => {
    let body: any
    let isMultipart = false
    if (form instanceof FormData) {
      let hasFile = false
      for (const value of form.values()) {
        if (typeof value !== 'string') {
          hasFile = true
          break
        }
      }
      if (hasFile) {
        body = form
        isMultipart = true
      } else {
        const params = new URLSearchParams()
        for (const [k, v] of form.entries()) {
          params.append(k, String(v))
        }
        body = params.toString()
      }
    } else {
      const params = new URLSearchParams()
      Object.entries(form).forEach(([k, v]) => {
        if (v !== undefined && v !== null) {
          if (Array.isArray(v)) {
            v.forEach((item) => params.append(k, String(item)))
          } else {
            params.append(k, String(v))
          }
        }
      })
      body = params.toString()
    }
    return apiRequest<T>(url, {
      method: 'POST',
      headers: isMultipart ? undefined : { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
  },
  delete: <T = any>(url: string, body?: any) => {
    const isForm = body instanceof FormData || body instanceof URLSearchParams
    return apiRequest<T>(url, {
      method: 'POST',
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
    })
  },
  uploadMedia: async (
    file: File,
    onProgress?: (percent: number, loaded: number, total: number) => void
  ): Promise<{ selection_id: string; filename: string; size: number }> => {
    const token = await getCsrfToken()
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/api/upload-media')
      xhr.withCredentials = true
      xhr.setRequestHeader('Content-Type', 'application/octet-stream')
      xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name))
      if (token) {
        xhr.setRequestHeader('x-csrf-token', token)
      }
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          const pct = Math.min(100, Math.round((e.loaded / e.total) * 100))
          onProgress(pct, e.loaded, e.total)
        }
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            reject(new Error('Invalid upload response'))
          }
        } else {
          let msg = `HTTP Error ${xhr.status}`
          try {
            const err = JSON.parse(xhr.responseText)
            msg = err.error || err.message || msg
          } catch {}
          reject(new Error(msg))
        }
      }
      xhr.onerror = () => reject(new Error('网络错误，上传失败'))
      xhr.onabort = () => reject(new Error('上传已取消'))
      xhr.send(file)
    })
  },
}
