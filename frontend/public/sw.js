const CACHE_NAME = 'subforge-shell-v1'
const SHELL_ASSETS = [
  '/',
  '/manifest.webmanifest',
  '/subforge-icon.svg',
  '/favicon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)).catch(() => {})
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  // Bypass API, media streaming (Range 206), SSE events, covers, and server pickers
  if (
    request.headers.has('range') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/picker/') ||
    url.pathname.startsWith('/tasks/') ||
    url.pathname.startsWith('/covers/') ||
    /\/tracks\/[^/]+\/media$/.test(url.pathname)
  ) {
    return
  }

  // Navigation requests: NetworkFirst with cached app shell fallback
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone()
            caches.open(CACHE_NAME).then((cache) => cache.put('/', copy))
          }
          return response
        })
        .catch(() => caches.match('/'))
    )
    return
  }

  // Hashed build assets & icons: StaleWhileRevalidate
  if (
    url.pathname.startsWith('/assets/') ||
    url.pathname.startsWith('/icons/') ||
    url.pathname.endsWith('.svg') ||
    url.pathname.endsWith('.png') ||
    url.pathname === '/manifest.webmanifest'
  ) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const networkFetch = fetch(request)
          .then((response) => {
            if (response.ok) {
              const copy = response.clone()
              caches.open(CACHE_NAME).then((cache) => cache.put(request, copy))
            }
            return response
          })
          .catch(() => cached)
        return cached || networkFetch
      })
    )
  }
})
