const CACHE_NAME = 'estacle-v1';
const OFFLINE_URL = '/offline';

const PRECACHE_ASSETS = [
  '/',
  '/offline',
  '/static/css/main.css',
  '/static/css/themes.css',
  '/static/js/app.js',
  '/static/js/api.js',
  '/static/js/socket.js',
  '/static/js/webrtc.js',
  '/static/js/ui.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS).catch(() => {
        // Some assets may fail, continue
      });
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET and API/WebSocket
  if (request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/socket.io')) return;
  if (url.pathname.startsWith('/uploads/')) {
    // Cache uploads with network-first
    event.respondWith(
      fetch(request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      }).catch(() => caches.match(request))
    );
    return;
  }

  // Network-first for HTML pages
  if (request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      }).catch(() => {
        return caches.match(request).then((cached) => {
          return cached || caches.match(OFFLINE_URL);
        });
      })
    );
    return;
  }

  // Cache-first for static assets
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok && (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      }).catch(() => caches.match(OFFLINE_URL));
    })
  );
});

// Push notifications
self.addEventListener('push', (event) => {
  let data = { title: 'ESTACLE', body: 'New notification' };
  try {
    if (event.data) {
      data = event.data.json();
    }
  } catch (e) {}

  const options = {
    body: data.body || '',
    icon: data.icon || '/static/icons/icon-192.png',
    badge: data.badge || '/static/icons/badge-72.png',
    data: data.data || {},
    tag: data.tag || 'estacle-notification',
    renotify: true,
    requireInteraction: data.requireInteraction || false,
    actions: data.actions || []
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'ESTACLE', options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  
  const data = event.notification.data || {};
  let url = '/chat';
  
  if (data.conversation_id) {
    url = `/chat?c=${data.conversation_id}`;
  } else if (data.call_id) {
    url = `/chat?call=${data.call_id}`;
  }

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes('/chat') && 'focus' in client) {
          client.postMessage({ type: 'notification_click', data });
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});

// Background sync for offline messages
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-messages') {
    event.waitUntil(
      self.clients.matchAll().then((clients) => {
        clients.forEach((client) => {
          client.postMessage({ type: 'sync_messages' });
        });
      })
    );
  }
});
