const CACHE_NAME = 'financelab-v6';

self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(cacheNames.map(name => caches.delete(name)));
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  if (!event.request.url.includes('/financelab')) return;
  
  // NEVER cache HTML pages - only cache static assets
  const url = event.request.url;
  const isPage = url.endsWith('/') || url.endsWith('.html') || !url.split('/financelab/')[1]?.includes('.');
  const isAsset = url.includes('.png') || url.includes('.json') || url.includes('.js') || url.includes('.woff');
  
  if (isPage || url.includes('/api')) return; // Don't cache pages or API calls
  
  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request).then(response => {
        if (!response || response.status !== 200) return response;
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        return response;
      });
    })
  );
});
